"""
DownloadsPanel  –  sidebar panel listing all torrents.

Layout:
  ┌─────────────────────────────┐
  │ DOWNLOADS              [+]  │   ← header
  ├─────────────────────────────┤
  │  [active download 1]        │   ↑ active transfers
  │  [active download 2]        │   │
  ├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
  │  [finished / paused 1]      │   ↓ completed / paused
  │  [finished / paused 2]      │
  └─────────────────────────────┘
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QFrame, QFileDialog, QDialog, QDialogButtonBox,
    QLineEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot

from core.torrent_engine import TorrentEngine, TorrentState
from interface.download_item_widget import DownloadItemWidget
from interface.icon_store import big_plus_icon, refresh_icon, ICON_SIZE_MEDIUM
from utils.logger import get_logger

log = get_logger("downloads_panel")

_ACTIVE_STATUSES = {"metadata", "downloading", "checking", "paused"}
_LOCAL_STATUS_FILE = Path.home() / ".novaplay" / "download_status_overrides.json"


class DownloadsPanel(QWidget):
    """Sidebar panel that reflects the state of the TorrentEngine."""

    def __init__(self, engine: TorrentEngine, parent=None):
        super().__init__(parent)
        self._engine  = engine
        # info_hash → (widget, last_status_category)
        self._items:  dict[str, DownloadItemWidget] = {}
        self._categ:  dict[str, str]                = {}   # "active" | "done"
        self._local_prefix = "local::"
        self._local_status_overrides: dict[str, str] = {}
        self._load_local_status_overrides()

        # Match the same sidebar surface color used by the library panel.
        self.setObjectName("sidebar_frame")
        self._build_ui()
        self._connect_engine()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(48)
        header.setObjectName("sidebar_header")

        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 8, 0)
        h_lay.setSpacing(4)

        title = QLabel("DOWNLOADS")
        title.setObjectName("title")
        h_lay.addWidget(title)
        h_lay.addStretch()

        refresh_btn = QPushButton()
        refresh_btn.setIcon(refresh_icon)
        refresh_btn.setIconSize(ICON_SIZE_MEDIUM)
        refresh_btn.setObjectName("icon_btn")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh downloads")
        refresh_btn.clicked.connect(self.refresh)
        h_lay.addWidget(refresh_btn)

        add_btn = QPushButton()
        add_btn.setIcon(big_plus_icon)
        add_btn.setIconSize(ICON_SIZE_MEDIUM)
        add_btn.setObjectName("icon_btn")
        add_btn.setFixedSize(32, 28)
        add_btn.setToolTip("Add magnet link or .torrent file")
        add_btn.clicked.connect(self._show_add_dialog)
        h_lay.addWidget(add_btn)

        root.addWidget(header)

        # ── Scrollable list ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setObjectName("sidebar_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_container = QWidget()
        self._list_container.setObjectName("sidebar_content")
        self._list_container.setAutoFillBackground(True)
        self._list_layout    = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        # Empty-state label (visible when list is empty)
        self._empty_lbl = QLabel(
            "No downloads yet.\n\nClick  +  to paste a magnet\nlink or open a .torrent file."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setObjectName("subtitle")
        self._empty_lbl.setContentsMargins(12, 24, 12, 8)
        self._list_layout.insertWidget(0, self._empty_lbl)

        scroll.setWidget(self._list_container)
        root.addWidget(scroll, stretch=1)

    def _connect_engine(self) -> None:
        self._engine.torrent_added.connect(self._on_torrent_added)
        self._engine.state_updated.connect(self._on_state_updated)
        self._engine.torrent_removed.connect(self._on_torrent_removed)
        # Populate panel with any historical entries loaded from disk
        self.refresh()

    def refresh(self) -> None:
        """Refresh from engine states and local download folder on demand."""
        for state in self._engine.all_states():
            self._on_torrent_added(state.info_hash)
            widget = self._items.get(state.info_hash)
            if widget is not None:
                widget.update_state(state)
                self._categ[state.info_hash] = self._category(state.status)
        self._sync_local_files()
        self._reorder()

    # ── Engine slots ───────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_torrent_added(self, info_hash: str) -> None:
        if info_hash in self._items:
            return
        state = self._engine.get_state(info_hash)
        if state is None:
            return

        self._empty_lbl.setVisible(False)

        widget = DownloadItemWidget(state)
        widget.pause_requested.connect(self._engine.pause)
        widget.resume_requested.connect(self._engine.resume)
        widget.remove_requested.connect(self._on_remove_requested)
        widget.delete_file_requested.connect(
            lambda h: self._engine.remove(h, delete_files=True)
        )

        self._items[info_hash]  = widget
        self._categ[info_hash]  = self._category(state.status)

        # New items always go to the top of their category group
        self._list_layout.insertWidget(0, widget)
        self._insert_separator_after(widget)
        self._sync_local_files()

    @pyqtSlot(str, object)
    def _on_state_updated(self, info_hash: str, state: TorrentState) -> None:
        widget = self._items.get(info_hash)
        if widget is None:
            return
        widget.update_state(state)

        # If an active torrent reaches completion, clear any prior local
        # "stopped" override for the same disk path.
        if state.status == "finished":
            local_hash = self._local_hash_for_state(state)
            if local_hash is not None and local_hash in self._local_status_overrides:
                self._local_status_overrides.pop(local_hash, None)
                self._save_local_status_overrides()

        new_cat = self._category(state.status)
        if new_cat != self._categ.get(info_hash):
            self._categ[info_hash] = new_cat
            self._reorder()

        # Refresh local entries so they remain in sync with on-disk contents.
        self._sync_local_files()

    @pyqtSlot(str)
    def _on_torrent_removed(self, info_hash: str) -> None:
        self._remove_item(info_hash)
        self._sync_local_files()

    @pyqtSlot(str)
    def _on_remove_requested(self, info_hash: str) -> None:
        state = self._engine.get_state(info_hash)
        if state is not None and state.status != "finished":
            local_hash = self._local_hash_for_state(state)
            if local_hash is not None:
                self._local_status_overrides[local_hash] = "stopped"
                self._save_local_status_overrides()
        self._engine.remove(info_hash)

    # ── Add dialog ─────────────────────────────────────────────────────────────

    def _show_add_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Download")
        dlg.setMinimumWidth(440)

        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Magnet link:"))
        magnet_edit = QLineEdit()
        magnet_edit.setPlaceholderText("magnet:?xt=urn:btih:…")
        lay.addWidget(magnet_edit)

        lay.addWidget(QLabel("— or —"))

        file_row = QHBoxLayout()
        file_edit = QLineEdit()
        file_edit.setPlaceholderText("Select a .torrent file…")
        file_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(
            lambda: file_edit.setText(
                QFileDialog.getOpenFileName(
                    dlg, "Open .torrent", "", "Torrent files (*.torrent)"
                )[0]
            )
        )
        file_row.addWidget(file_edit)
        file_row.addWidget(browse_btn)
        lay.addLayout(file_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)

        if dlg.exec():
            text     = magnet_edit.text().strip()
            filepath = file_edit.text().strip()
            if text.startswith("magnet:"):
                self._engine.add_magnet(text)
            elif filepath:
                self._engine.add_torrent_file(filepath)

    # ── Ordering helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _category(status: str) -> str:
        return "active" if status in _ACTIVE_STATUSES else "done"

    def _is_local_hash(self, info_hash: str) -> bool:
        return info_hash.startswith(self._local_prefix)

    def _download_dir(self) -> Path:
        # Use active engine save path when available, else default fallback.
        save_path = getattr(self._engine, "_save_path", None) or str(
            Path.home() / "Downloads" / "NovaPlay"
        )
        return Path(save_path)

    def _local_hash(self, path: Path) -> str:
        return f"{self._local_prefix}{path}"

    def _local_hash_for_state(self, state: TorrentState) -> str | None:
        if not state.save_path or not state.name:
            return None
        return self._local_hash(Path(state.save_path) / state.name)

    def _load_local_status_overrides(self) -> None:
        try:
            if not _LOCAL_STATUS_FILE.exists():
                return
            data = json.loads(_LOCAL_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._local_status_overrides = {
                    str(k): "stopped"
                    for k, v in data.items()
                    if v == "stopped" and str(k).startswith(self._local_prefix)
                }
        except Exception:
            log.exception("Failed to load local download status overrides")
            self._local_status_overrides = {}

    def _save_local_status_overrides(self) -> None:
        try:
            _LOCAL_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _LOCAL_STATUS_FILE.write_text(
                json.dumps(self._local_status_overrides, indent=2),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save local download status overrides")

    def _existing_torrent_names(self) -> set[str]:
        return {
            s.name.strip().lower()
            for s in self._engine.all_states()
            if (s.name or "").strip()
        }

    def _path_size(self, path: Path) -> int:
        try:
            if path.is_file():
                return path.stat().st_size
            total = 0
            if path.is_dir():
                for p in path.rglob("*"):
                    if p.is_file():
                        try:
                            total += p.stat().st_size
                        except OSError:
                            continue
            return total
        except OSError:
            return 0

    def _make_local_state(self, path: Path, status: str = "finished") -> TorrentState:
        size = self._path_size(path)
        return TorrentState(
            info_hash=self._local_hash(path),
            name=path.name,
            total_size=size,
            downloaded_bytes=size,
            progress=1.0,
            status=status,
            save_path=str(path.parent),
            added_time=path.stat().st_mtime if path.exists() else 0.0,
        )

    def _add_local_item(self, path: Path) -> None:
        local_hash = self._local_hash(path)
        state = self._make_local_state(
            path,
            status=self._local_status_overrides.get(local_hash, "finished"),
        )
        widget = DownloadItemWidget(state)
        widget.remove_requested.connect(self._on_local_remove_requested)
        widget.delete_file_requested.connect(self._on_local_delete_requested)

        self._items[state.info_hash] = widget
        self._categ[state.info_hash] = "done"
        self._list_layout.insertWidget(0, widget)
        self._insert_separator_after(widget)

    @pyqtSlot(str)
    def _on_local_remove_requested(self, info_hash: str) -> None:
        self._remove_item(info_hash)

    @pyqtSlot(str)
    def _on_local_delete_requested(self, info_hash: str) -> None:
        self._local_status_overrides.pop(info_hash, None)
        self._save_local_status_overrides()
        self._remove_item(info_hash)
        self._sync_local_files()

    def _sync_local_files(self) -> None:
        download_dir = self._download_dir()
        if not download_dir.exists():
            return

        torrent_names = self._existing_torrent_names()
        disk_paths = [
            p for p in sorted(download_dir.iterdir(), key=lambda x: x.name.lower())
            if not p.name.startswith(".")
        ]
        local_hashes_on_disk = {self._local_hash(p) for p in disk_paths}

        # Forget status overrides for files that no longer exist.
        overrides_changed = False
        for h in list(self._local_status_overrides):
            if h not in local_hashes_on_disk:
                self._local_status_overrides.pop(h, None)
                overrides_changed = True
        if overrides_changed:
            self._save_local_status_overrides()

        # Add files/folders on disk that are not represented by torrent states.
        for path in disk_paths:
            if path.name.strip().lower() in torrent_names:
                continue
            h = self._local_hash(path)
            if h not in self._items:
                self._add_local_item(path)

        # Remove stale local entries that no longer exist on disk.
        stale = [
            h for h in self._items
            if self._is_local_hash(h) and h not in local_hashes_on_disk
        ]
        for h in stale:
            self._remove_item(h)

        self._empty_lbl.setVisible(not bool(self._items))

    def _reorder(self) -> None:
        """
        Re-sort the list so active downloads appear above completed/paused ones.
        Within each group items are ordered newest first (by their position in
        self._items, which preserves insertion order on Python 3.7+).
        """
        if not self._items:
            return

        # Collect all current widgets from the layout (skip separators + stretch)
        ordered = list(self._items.values())
        active  = [w for w in ordered if self._categ.get(
            next(h for h, v in self._items.items() if v is w), ""
        ) == "active"]
        done    = [w for w in ordered if w not in active]
        new_order = active + done

        # Remove everything from layout (except the trailing stretch)
        for w in ordered:
            self._list_layout.removeWidget(w)
        # Remove all separators
        for i in reversed(range(self._list_layout.count() - 1)):   # skip stretch
            item = self._list_layout.itemAt(i)
            if item and isinstance(item.widget(), _Separator):
                item.widget().deleteLater()
                self._list_layout.removeItem(item)

        # Re-insert in sorted order
        for pos, w in enumerate(new_order):
            self._list_layout.insertWidget(pos * 2, w)
            self._insert_separator_after(w)

    def _remove_item(self, info_hash: str) -> None:
        widget = self._items.pop(info_hash, None)
        self._categ.pop(info_hash, None)
        if widget is None:
            return

        idx = self._list_layout.indexOf(widget)
        if idx >= 0:
            next_item = self._list_layout.itemAt(idx + 1)
            if next_item and isinstance(next_item.widget(), _Separator):
                self._list_layout.removeItem(next_item)
                next_item.widget().deleteLater()
        self._list_layout.removeWidget(widget)
        widget.deleteLater()
        self._empty_lbl.setVisible(not bool(self._items))

    def _insert_separator_after(self, widget: QWidget) -> None:
        idx = self._list_layout.indexOf(widget)
        if idx >= 0:
            sep = _Separator()
            self._list_layout.insertWidget(idx + 1, sep)


class _Separator(QFrame):
    """1px horizontal rule between download items."""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet("background:#2a2a45;border:none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
