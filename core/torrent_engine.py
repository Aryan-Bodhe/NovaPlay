"""
TorrentEngine  –  thin Qt wrapper around a libtorrent session.

Runs entirely on the main thread; a QTimer polls libtorrent alerts every
second so no extra threads are needed.  All public methods are safe to call
when libtorrent is unavailable (ImportError) – they log a warning and return.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from utils.logger import get_logger

log = get_logger("torrent_engine")

# ── Optional libtorrent import ────────────────────────────────────────────────
try:
    import libtorrent as lt          # type: ignore
    _LT_OK = True
except ImportError:
    lt = None                        # type: ignore
    _LT_OK = False
    log.warning("libtorrent not installed – download panel will be disabled")

DEFAULT_SAVE_PATH = str(Path.home() / "Downloads" / "NovaPlay")
_HISTORY_FILE     = Path.home() / ".novaplay" / "downloads.json"


# ── Data transfer object ───────────────────────────────────────────────────────

@dataclass
class TorrentState:
    info_hash:        str
    name:             str
    total_size:       int    = 0      # bytes
    downloaded_bytes: int    = 0      # bytes actually downloaded
    progress:         float  = 0.0   # 0.0 – 1.0
    download_rate:    int    = 0      # bytes / s
    upload_rate:      int    = 0      # bytes / s
    num_seeds:        int    = 0
    num_peers:        int    = 0
    eta_seconds:      int    = -1     # -1 = unknown
    # "metadata" | "downloading" | "seeding" | "paused"
    # | "checking" | "finished" | "error"
    status:           str    = "metadata"
    save_path:        str    = ""
    added_time:       float  = field(default_factory=time.time)
    error_msg:        str    = ""


# ── Engine ─────────────────────────────────────────────────────────────────────

class TorrentEngine(QObject):
    """
    Wraps a libtorrent session and exposes Qt signals for UI updates.

    Lifecycle:
        engine = TorrentEngine(save_path="~/Downloads/NovaPlay")
        # ... connect signals ...
        # On app close:
        engine.shutdown()
    """

    torrent_added   = pyqtSignal(str)          # info_hash
    state_updated   = pyqtSignal(str, object)  # info_hash, TorrentState
    torrent_removed = pyqtSignal(str)          # info_hash
    error_occurred  = pyqtSignal(str, str)     # info_hash, message

    # Maps lt state enum → our string label
    _LT_STATE: dict = {}

    def __init__(self, save_path: str = DEFAULT_SAVE_PATH, parent=None):
        super().__init__(parent)
        self._save_path  = save_path
        self._handles:    dict[str, object]       = {}   # info_hash -> lt.torrent_handle
        self._states:     dict[str, TorrentState] = {}   # info_hash -> TorrentState
        self._user_paused: set[str]               = set()  # hashes explicitly paused by user
        self._completed:   set[str]               = set()  # hashes auto-stopped on completion

        # Load persisted history before starting the session
        self._load_history()

        if not _LT_OK:
            return

        Path(save_path).mkdir(parents=True, exist_ok=True)

        self._session = lt.session()
        self._session.apply_settings({
            "listen_interfaces": "0.0.0.0:6881,[::]:6881",
            "alert_mask": lt.alert.category_t.all_categories,
        })

        TorrentEngine._LT_STATE = {
            lt.torrent_status.checking_files:       "checking",
            lt.torrent_status.downloading_metadata: "metadata",
            lt.torrent_status.downloading:          "downloading",
            lt.torrent_status.finished:             "finished",
            lt.torrent_status.seeding:              "seeding",
            lt.torrent_status.allocating:           "checking",
            lt.torrent_status.checking_resume_data: "checking",
        }

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        log.info("TorrentEngine started (save_path=%s)", save_path)

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return _LT_OK

    def add_magnet(self, uri: str, save_path: str | None = None) -> str | None:
        if not _LT_OK:
            log.warning("libtorrent unavailable – cannot add magnet")
            return None
        try:
            params = lt.parse_magnet_uri(uri)
            params.save_path = save_path or self._save_path
            handle = self._session.add_torrent(params)
            info_hash = str(handle.info_hash())
            self._handles[info_hash] = handle
            # If we had a history entry for this hash, preserve added_time
            prev = self._states.get(info_hash)
            self._states[info_hash] = TorrentState(
                info_hash=info_hash,
                name=getattr(params, "name", "") or "Fetching metadata…",
                save_path=params.save_path,
                status="metadata",
                added_time=prev.added_time if prev else time.time(),
            )
            self._completed.discard(info_hash)
            self.torrent_added.emit(info_hash)
            log.info("Magnet added: %s", info_hash)
            return info_hash
        except Exception:
            log.exception("Failed to add magnet: %s", uri[:80])
            return None

    def add_torrent_file(self, filepath: str, save_path: str | None = None) -> str | None:
        if not _LT_OK:
            log.warning("libtorrent unavailable – cannot add torrent file")
            return None

    def set_save_path(self, save_path: str) -> None:
        """Update default save path for newly added torrents."""
        self._save_path = save_path
        try:
            Path(save_path).mkdir(parents=True, exist_ok=True)
        except Exception:
            log.exception("Failed to create download directory: %s", save_path)
        try:
            info   = lt.torrent_info(filepath)
            params = lt.add_torrent_params()
            params.ti        = info
            params.save_path = save_path or self._save_path
            handle = self._session.add_torrent(params)
            info_hash = str(handle.info_hash())
            self._handles[info_hash] = handle
            prev = self._states.get(info_hash)
            self._states[info_hash] = TorrentState(
                info_hash=info_hash,
                name=info.name(),
                total_size=info.total_size(),
                save_path=params.save_path,
                status="checking",
                added_time=prev.added_time if prev else time.time(),
            )
            self._completed.discard(info_hash)
            self.torrent_added.emit(info_hash)
            log.info("Torrent file added: %s", info.name())
            return info_hash
        except Exception:
            log.exception("Failed to add torrent file: %s", filepath)
            return None

    def pause(self, info_hash: str) -> None:
        """User-initiated pause.  Records intent so _poll won't auto-resume."""
        self._user_paused.add(info_hash)
        handle = self._handles.get(info_hash)
        if handle and handle.is_valid():
            handle.pause()
            if info_hash in self._states:
                self._states[info_hash].status = "paused"
                self.state_updated.emit(info_hash, self._states[info_hash])

    def resume(self, info_hash: str) -> None:
        """User-initiated resume.  Clears the paused intent."""
        self._user_paused.discard(info_hash)
        handle = self._handles.get(info_hash)
        if handle and handle.is_valid():
            handle.resume()

    def remove(self, info_hash: str, delete_files: bool = False) -> None:
        self._user_paused.discard(info_hash)
        self._completed.discard(info_hash)
        handle = self._handles.pop(info_hash, None)
        self._states.pop(info_hash, None)
        if handle and handle.is_valid():
            flags = lt.session.delete_files if delete_files else 0
            self._session.remove_torrent(handle, flags)
        self.torrent_removed.emit(info_hash)
        self._save_history()
        log.info("Removed torrent %s (delete_files=%s)", info_hash, delete_files)

    def get_state(self, info_hash: str) -> TorrentState | None:
        return self._states.get(info_hash)

    def all_states(self) -> list[TorrentState]:
        return list(self._states.values())

    def emit_all_states(self) -> None:
        """Emit torrent_added for every known state (historical + active).
        Call this once after connecting panel signals to populate the UI."""
        for info_hash in list(self._states):
            self.torrent_added.emit(info_hash)

    def shutdown(self) -> None:
        if not _LT_OK:
            self._save_history()
            return
        self._timer.stop()
        self._session.pause()
        self._save_history()
        log.info("TorrentEngine shut down")

    # ── History persistence ────────────────────────────────────────────────────

    def _save_history(self) -> None:
        try:
            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(s) for s in self._states.values()]
            _HISTORY_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            log.exception("Failed to save download history")

    def _load_history(self) -> None:
        if not _HISTORY_FILE.exists():
            return
        try:
            data = json.loads(_HISTORY_FILE.read_text())
            for entry in data:
                # Ensure all fields exist (handle older history files missing new fields)
                entry.setdefault("downloaded_bytes", 0)
                ts = TorrentState(**entry)
                # Historical entries without an active handle are shown as-is.
                # If they were mid-download, mark them paused so the UI is honest.
                if ts.status in ("downloading", "metadata", "checking"):
                    ts.status = "paused"
                self._states[ts.info_hash] = ts
            log.info("Loaded %d entries from download history", len(self._states))
        except Exception:
            log.exception("Failed to load download history")

    # ── Internal poll ──────────────────────────────────────────────────────────

    def _poll(self) -> None:
        for info_hash, handle in list(self._handles.items()):
            if not handle.is_valid():
                continue
            try:
                s         = handle.status()
                is_paused = s.paused

                # ── Fix #1: Re-apply user pause if libtorrent auto-resumed ──
                if not is_paused and info_hash in self._user_paused:
                    handle.pause()
                    is_paused = True

                raw_state = self._LT_STATE.get(s.state, "downloading")

                # ── Fix #3: Auto-stop seeding / finished torrents ──────────
                if raw_state in ("seeding", "finished") and info_hash not in self._completed:
                    self._completed.add(info_hash)
                    handle.pause()
                    is_paused = True
                    log.info("Auto-stopped completed torrent %s", info_hash)
                    self._save_history()

                state_str = (
                    "paused"    if is_paused and info_hash not in self._completed
                    else "finished" if info_hash in self._completed
                    else raw_state
                )

                total            = s.total_wanted or 0
                downloaded_bytes = int(total * float(s.progress))
                progress         = float(s.progress)

                if not is_paused and s.download_rate > 0 and progress < 1.0:
                    remaining   = total * (1.0 - progress)
                    eta_seconds = int(remaining / s.download_rate)
                else:
                    eta_seconds = -1

                prev = self._states.get(info_hash)
                ts = TorrentState(
                    info_hash=info_hash,
                    name=s.name or (prev.name if prev else ""),
                    total_size=total,
                    downloaded_bytes=downloaded_bytes,
                    progress=progress,
                    download_rate=s.download_rate if not is_paused else 0,
                    upload_rate=s.upload_rate   if not is_paused else 0,
                    num_seeds=s.num_seeds,
                    num_peers=s.num_peers,
                    eta_seconds=eta_seconds,
                    status=state_str,
                    save_path=prev.save_path if prev else self._save_path,
                    added_time=prev.added_time if prev else time.time(),
                )
                self._states[info_hash] = ts
                self.state_updated.emit(info_hash, ts)
            except Exception:
                log.exception("Error polling torrent %s", info_hash)
