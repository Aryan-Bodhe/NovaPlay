"""
DownloadItemWidget  –  a single row in the downloads list.

Collapsed (default):
  ┌──────────────────────────────────────────┐
  │ Movie Name…               [⏸] [✕]       │
  │ ████████░░  80%  ↓ 2.3 MB/s             │
  └──────────────────────────────────────────┘

Expanded (active items only — click row body to toggle):
  ┌──────────────────────────────────────────┐
  │ Movie Name…               [⏸] [✕]       │
  │ ████████░░  80%  ↓ 2.3 MB/s             │
  │  Seeds: 42   Peers: 8   ETA: 5m 30s     │
  │  Downloaded: 6.6 GB / 8.2 GB (80%)      │
  │  → ~/Downloads/NovaPlay               │
  └──────────────────────────────────────────┘

Finished (not expandable):
  ┌──────────────────────────────────────────┐
  │ Movie Name…               [🗑]           │
  │ ✓ Finished  ·  8.2 GB                   │
  └──────────────────────────────────────────┘
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from core.torrent_engine import TorrentState
from interface.icon_store import (
    pause_icon, play_icon, stop_icon, trash_icon,
    ICON_SIZE_SMALL,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_bytes(b: int) -> str:
    if b <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024  # type: ignore[assignment]
    return f"{b:.1f} PB"


def _fmt_speed(bps: int) -> str:
    return f"{_fmt_bytes(bps)}/s"


def _fmt_eta(secs: int) -> str:
    if secs < 0:
        return "–"
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


_STATUS_TEXT = {
    "metadata":    "Fetching metadata…",
    "downloading": "Downloading",
    "seeding":     "Seeding",
    "paused":      "Paused",
    "stopped":     "Stopped",
    "checking":    "Checking files…",
    "finished":    "Finished",
    "error":       "Error",
}


# ── Eliding label ──────────────────────────────────────────────────────────────

class _ElidedLabel(QLabel):
    """
    A label that always elides its text to the available width.

    We never call setText() so the label's sizeHint() width is always 0 —
    it can never push the parent layout wider than the container.
    The actual text is painted manually in paintEvent() using the real
    pixel width of the widget at draw time.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._txt = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def set_text(self, text: str) -> None:
        self._txt = text
        self.setToolTip(text)
        self.update()

    # Return a zero-width hint so the label never forces the layout wider.
    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        sh.setWidth(0)
        return sh

    def minimumSizeHint(self) -> QSize:
        msh = super().minimumSizeHint()
        msh.setWidth(0)
        return msh

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        fm      = self.fontMetrics()
        elided  = fm.elidedText(self._txt, Qt.TextElideMode.ElideRight,
                                self.contentsRect().width())
        painter.drawText(self.contentsRect(),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         elided)


# ── Delete confirmation dialog ─────────────────────────────────────────────────

class _DeleteConfirmDialog(QDialog):
    """
    Themed confirmation dialog for deleting a finished download.

    After exec(), read `.action`:
        "delete"  – user chose Delete File
        "remove"  – user chose Remove from List
        "cancel"  – user dismissed / pressed Cancel
    """

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.action = "cancel"

        self.setWindowTitle("Delete file?")
        self.setFixedWidth(400)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._build_ui(filename)

    def _build_ui(self, filename: str) -> None:
        self.setObjectName("delete_dialog")
        self.setStyleSheet("""
            QDialog#delete_dialog {
                background-color: #1a1a2e;
                border: 1px solid #2d2d50;
                border-radius: 12px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 22)
        root.setSpacing(0)

        # ── Icon ──────────────────────────────────────────────────────────────
        icon_lbl = QLabel()
        icon_lbl.setPixmap(
            trash_icon.pixmap(QSize(42, 42))
        )
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(icon_lbl)
        root.addSpacing(14)

        # ── Title ─────────────────────────────────────────────────────────────
        title = QLabel("Delete file from disk?")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #e0e0f0; background: transparent;"
        )
        root.addWidget(title)
        root.addSpacing(8)

        # ── Filename ──────────────────────────────────────────────────────────
        name_lbl = QLabel(filename)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "font-size: 12px; color: #c77dff; background: transparent;"
        )
        root.addWidget(name_lbl)
        root.addSpacing(12)

        # ── Description ───────────────────────────────────────────────────────
        desc = QLabel(
            "This will permanently delete the file from your\n"
            "downloads folder and cannot be undone."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            "font-size: 12px; color: #8080aa; background: transparent;"
        )
        root.addWidget(desc)
        root.addSpacing(22)

        # ── Divider ───────────────────────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: #2a2a45; border: none;")
        root.addWidget(line)
        root.addSpacing(18)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a45;
                border: 1px solid #3a3a60;
                border-radius: 6px;
                color: #e0e0f0;
                font-size: 12px;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #3a3a65; border-color: #7c3aed; }
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        remove_btn = QPushButton("Remove from List")
        remove_btn.setFixedHeight(34)
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a45;
                border: 1px solid #3a3a60;
                border-radius: 6px;
                color: #e0e0f0;
                font-size: 12px;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #3a3a65; border-color: #7c3aed; }
        """)
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(remove_btn)

        delete_btn = QPushButton("Delete File")
        delete_btn.setFixedHeight(34)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b1a1a;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                padding: 0 16px;
            }
            QPushButton:hover { background-color: #b02020; }
            QPushButton:pressed { background-color: #6b1010; }
        """)
        delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(delete_btn)

        root.addLayout(btn_row)

    def _on_cancel(self)  -> None: self.action = "cancel";  self.reject()
    def _on_remove(self)  -> None: self.action = "remove";  self.accept()
    def _on_delete(self)  -> None: self.action = "delete";  self.accept()


# ── Widget ─────────────────────────────────────────────────────────────────────

class DownloadItemWidget(QFrame):
    """
    One row in the downloads panel.
    - Active/paused items: click body to expand/collapse detail.
    - Finished items: not expandable; trash button deletes file after confirm.
    """

    pause_requested       = pyqtSignal(str)
    resume_requested      = pyqtSignal(str)
    remove_requested      = pyqtSignal(str)   # keep file on disk
    delete_file_requested = pyqtSignal(str)   # remove from list AND delete file

    def __init__(self, state: TorrentState, parent=None):
        super().__init__(parent)
        self._info_hash = state.info_hash
        self._expanded  = False
        self._paused    = (state.status == "paused")
        self._finished  = (state.status == "finished")
        self._save_path = state.save_path

        self.setObjectName("download_item")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._build_ui()
        self.update_state(state)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 8, 8)
        root.setSpacing(4)

        # ── Top row: [name (stretches)] [pause] [action] ─────────────────────
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)

        self._name_lbl = _ElidedLabel()
        self._name_lbl.setObjectName("dl_name")
        top.addWidget(self._name_lbl, stretch=1)

        self._pause_btn = QPushButton()
        self._pause_btn.setIconSize(ICON_SIZE_SMALL)
        self._pause_btn.setObjectName("icon_btn")
        self._pause_btn.setFixedSize(22, 22)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        top.addWidget(self._pause_btn)

        self._action_btn = QPushButton()
        self._action_btn.setIconSize(ICON_SIZE_SMALL)
        self._action_btn.setObjectName("icon_btn")
        self._action_btn.setFixedSize(22, 22)
        self._action_btn.clicked.connect(self._on_action_clicked)
        top.addWidget(self._action_btn)

        root.addLayout(top)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setObjectName("dl_progress")
        self._progress.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._progress.setMinimumWidth(0)
        root.addWidget(self._progress)

        # ── Status line ────────────────────────────────────────────────────────
        self._status_lbl = QLabel()
        self._status_lbl.setObjectName("dl_status")
        self._status_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._status_lbl.setMinimumWidth(0)
        root.addWidget(self._status_lbl)

        # ── Collapsible detail ────────────────────────────────────────────────
        self._detail = QFrame()
        self._detail.setVisible(False)
        detail_lay = QVBoxLayout(self._detail)
        detail_lay.setContentsMargins(0, 6, 0, 0)
        detail_lay.setSpacing(2)

        self._seeds_lbl      = QLabel()
        self._eta_lbl        = QLabel()
        self._downloaded_lbl = QLabel()
        self._path_lbl       = QLabel()
        self._path_lbl.setWordWrap(True)

        for lbl in (self._seeds_lbl, self._eta_lbl, self._downloaded_lbl, self._path_lbl):
            lbl.setObjectName("dl_detail_lbl")
            detail_lay.addWidget(lbl)

        root.addWidget(self._detail)

    # ── Public ─────────────────────────────────────────────────────────────────

    def update_state(self, state: TorrentState) -> None:
        self._paused    = (state.status == "paused")
        self._finished  = (state.status in ("finished", "stopped"))
        self._save_path = state.save_path

        # Name (always first — _ElidedLabel repaints itself with correct width)
        self._name_lbl.set_text(state.name or "Unknown")

        if self._finished:
            self._pause_btn.setVisible(False)
            self._detail.setVisible(False)
            self._expanded = False
            self._progress.setVisible(False)

            self._action_btn.setIcon(trash_icon)
            self._action_btn.setToolTip("Delete file…")

            self._progress.setValue(1000)
            if state.status == "finished":
                self._status_lbl.setText(
                    f"✓ Finished  ·  {_fmt_bytes(state.total_size)}"
                )
            else:
                size = state.downloaded_bytes or state.total_size
                self._status_lbl.setText(f"✕ Stopped  ·  {_fmt_bytes(size)}")

        else:
            self._pause_btn.setVisible(True)
            self._progress.setVisible(True)

            if self._paused:
                self._pause_btn.setIcon(play_icon)
                self._pause_btn.setToolTip("Resume")
            else:
                self._pause_btn.setIcon(pause_icon)
                self._pause_btn.setToolTip("Pause")

            self._action_btn.setIcon(stop_icon)
            self._action_btn.setToolTip("Stop and remove from list")

            self._progress.setValue(int(state.progress * 1000))

            pct = int(state.progress * 100)
            if state.status == "downloading":
                self._status_lbl.setText(
                    f"{pct}%  ↓ {_fmt_speed(state.download_rate)}"
                    f"  ↑ {_fmt_speed(state.upload_rate)}"
                )
            elif state.status == "paused":
                self._status_lbl.setText("Paused")
            else:
                self._status_lbl.setText(_STATUS_TEXT.get(state.status, state.status))

            # Detail section (kept current even when collapsed)
            self._seeds_lbl.setText(f"Seeds: {state.num_seeds}   Peers: {state.num_peers}")
            self._eta_lbl.setText(f"ETA: {_fmt_eta(state.eta_seconds)}")
            self._downloaded_lbl.setText(
                f"Downloaded: {_fmt_bytes(state.downloaded_bytes)} / "
                f"{_fmt_bytes(state.total_size)}  ({pct}%)"
            )
            self._path_lbl.setText(f"→ {state.save_path}")

    # ── Events ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if not self._finished:
            self._expanded = not self._expanded
            self._detail.setVisible(self._expanded)
        super().mousePressEvent(event)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _on_pause_clicked(self) -> None:
        if self._paused:
            self.resume_requested.emit(self._info_hash)
        else:
            self.pause_requested.emit(self._info_hash)

    def _on_action_clicked(self) -> None:
        if self._finished:
            self._on_delete_clicked()
        else:
            self.remove_requested.emit(self._info_hash)

    def _on_delete_clicked(self) -> None:
        name = self._name_lbl._txt or "this file"
        dlg  = _DeleteConfirmDialog(name, parent=self)
        dlg.exec()
        if dlg.action == "delete":
            self._delete_files_from_disk()
            self.delete_file_requested.emit(self._info_hash)
        elif dlg.action == "remove":
            self.remove_requested.emit(self._info_hash)

    def _delete_files_from_disk(self) -> None:
        """Best-effort removal of the downloaded file/folder from disk."""
        name = self._name_lbl._txt
        if not self._save_path or not name:
            return
        target = Path(self._save_path) / name
        try:
            if target.is_dir():
                import shutil
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
        except Exception:
            pass
