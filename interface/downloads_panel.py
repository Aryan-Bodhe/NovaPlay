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

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QFrame, QFileDialog, QDialog, QDialogButtonBox,
    QLineEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot

from core.torrent_engine import TorrentEngine, TorrentState
from interface.download_item_widget import DownloadItemWidget
from interface.icon_store import plus_icon, ICON_SIZE
from utils.logger import get_logger

log = get_logger("downloads_panel")

_ACTIVE_STATUSES = {"metadata", "downloading", "checking", "paused"}


class DownloadsPanel(QWidget):
    """Sidebar panel that reflects the state of the TorrentEngine."""

    def __init__(self, engine: TorrentEngine, parent=None):
        super().__init__(parent)
        self._engine  = engine
        # info_hash → (widget, last_status_category)
        self._items:  dict[str, DownloadItemWidget] = {}
        self._categ:  dict[str, str]                = {}   # "active" | "done"

        self.setObjectName("explorer_panel")   # reuse sidebar styling
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

        add_btn = QPushButton()
        add_btn.setIcon(plus_icon)
        add_btn.setIconSize(ICON_SIZE)
        add_btn.setObjectName("icon_btn")
        add_btn.setFixedSize(32, 28)
        add_btn.setToolTip("Add magnet link or .torrent file")
        add_btn.clicked.connect(self._show_add_dialog)
        h_lay.addWidget(add_btn)

        root.addWidget(header)

        # ── Scrollable list ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._list_container = QWidget()
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
        self._engine.emit_all_states()

    # ── Engine slots ───────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_torrent_added(self, info_hash: str) -> None:
        state = self._engine.get_state(info_hash)
        if state is None:
            return

        self._empty_lbl.setVisible(False)

        widget = DownloadItemWidget(state)
        widget.pause_requested.connect(self._engine.pause)
        widget.resume_requested.connect(self._engine.resume)
        widget.remove_requested.connect(self._engine.remove)
        widget.delete_file_requested.connect(
            lambda h: self._engine.remove(h, delete_files=True)
        )

        self._items[info_hash]  = widget
        self._categ[info_hash]  = self._category(state.status)

        # New items always go to the top of their category group
        self._list_layout.insertWidget(0, widget)
        self._insert_separator_after(widget)

    @pyqtSlot(str, object)
    def _on_state_updated(self, info_hash: str, state: TorrentState) -> None:
        widget = self._items.get(info_hash)
        if widget is None:
            return
        widget.update_state(state)

        new_cat = self._category(state.status)
        if new_cat != self._categ.get(info_hash):
            self._categ[info_hash] = new_cat
            self._reorder()

    @pyqtSlot(str)
    def _on_torrent_removed(self, info_hash: str) -> None:
        widget = self._items.pop(info_hash, None)
        self._categ.pop(info_hash, None)
        if widget:
            # Also remove any separator that immediately follows it
            idx = self._list_layout.indexOf(widget)
            if idx >= 0:
                next_item = self._list_layout.itemAt(idx + 1)
                if next_item and isinstance(next_item.widget(), _Separator):
                    self._list_layout.removeItem(next_item)
                    next_item.widget().deleteLater()
            self._list_layout.removeWidget(widget)
            widget.deleteLater()

        if not self._items:
            self._empty_lbl.setVisible(True)

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
