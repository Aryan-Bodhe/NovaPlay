from pathlib import Path

from PyQt6.QtCore import Qt, QPoint, QRect, QEvent
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QLabel, QDialogButtonBox,
    QLineEdit, QWidget, QFrame, QApplication,
)

from interface.icon_store import dropdown_icon, ICON_SIZE_SMALL


class _ThemeSelector(QWidget):
    """
    Button-only widget. The floating dropdown panel is owned and positioned
    by SettingsDialog so it overlays sibling widgets — no native popup window,
    no X11/Wayland input grab, no system-wide freeze.
    """

    OPTIONS = [
        ("purple", "Purple Dark (Default)"),
        ("vscode",  "VS Code Dark"),
    ]

    def __init__(self, theme: str, parent=None):
        super().__init__(parent)
        self._value = theme if any(k == theme for k, _ in self.OPTIONS) else "purple"
        self._panel: QFrame | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._btn = QPushButton()
        self._btn.setObjectName("theme_sel_btn")
        self._btn.setIcon(dropdown_icon)
        self._btn.setIconSize(ICON_SIZE_SMALL)
        self._btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            "QPushButton#theme_sel_btn { text-align: left; padding: 6px 10px; }"
        )
        self._btn.clicked.connect(self._toggle)
        layout.addWidget(self._btn)
        self._refresh()

    def attach_panel(self, panel: QFrame):
        self._panel = panel

    def _toggle(self):
        if self._panel is None:
            return
        if self._panel.isVisible():
            self._panel.hide()
            return
        # Position the panel flush below this widget, in dialog coordinates
        dialog = self.window()
        pos = self.mapTo(dialog, QPoint(0, self.height()))
        self._panel.setFixedWidth(self.width())
        self._panel.move(pos)
        self._panel.show()
        self._panel.raise_()

    def set_value(self, value: str):
        self._value = value
        self._refresh()

    def _refresh(self):
        label = next(lbl for k, lbl in self.OPTIONS if k == self._value)
        self._btn.setText(label)

    def value(self) -> str:
        return self._value


class SettingsDialog(QDialog):
    """Application settings dialog (theme, download directory, watch directories)."""

    def __init__(
        self,
        theme: str,
        download_dir: str,
        watch_dirs: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(620, 460)
        self.setModal(True)

        self._dirs = list(watch_dirs)
        self._build_ui(theme=theme, download_dir=download_dir)

        # Watch for clicks anywhere in the app to dismiss the floating panel
        QApplication.instance().installEventFilter(self)

    def _build_ui(self, theme: str, download_dir: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("Settings")
        header.setObjectName("title")
        layout.addWidget(header)

        subtitle = QLabel("Theme, download location, and library folders.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Theme")
        self._theme_selector = _ThemeSelector(theme)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_selector, stretch=1)
        layout.addLayout(theme_row)

        dl_lbl = QLabel("Download Folder")
        layout.addWidget(dl_lbl)
        dl_row = QHBoxLayout()
        self._download_edit = QLineEdit(download_dir)
        self._download_edit.setPlaceholderText(str(Path.home() / "Downloads" / "NovaPlay"))
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_download_dir)
        dl_row.addWidget(self._download_edit, stretch=1)
        dl_row.addWidget(browse_btn)
        layout.addLayout(dl_row)

        dirs_header = QLabel("Watch Directories")
        dirs_header.setObjectName("title")
        layout.addWidget(dirs_header)

        desc = QLabel("NovaPlay scans these directories for series and movies.")
        desc.setObjectName("subtitle")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._list_widget = QListWidget()
        for d in self._dirs:
            self._list_widget.addItem(QListWidgetItem(d))
        layout.addWidget(self._list_widget, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("+ Add Directory")
        add_btn.setObjectName("accent")
        add_btn.clicked.connect(self._add_dir)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)

        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        # ── Floating dropdown panel ───────────────────────────────────────────
        # Parented to the dialog so it renders above sibling widgets via raise_(),
        # but is NOT a top-level window — no native popup, no input grab.
        self._theme_panel = QFrame(self)
        self._theme_panel.setObjectName("theme_sel_panel")
        self._theme_panel.setFrameShape(QFrame.Shape.NoFrame)
        self._theme_panel.setStyleSheet(
            "QFrame#theme_sel_panel { border-radius: 0 0 6px 6px; }"
        )

        p_layout = QVBoxLayout(self._theme_panel)
        p_layout.setContentsMargins(0, 0, 0, 0)
        p_layout.setSpacing(0)

        self._theme_list = QListWidget()
        self._theme_list.setObjectName("theme_sel_list")
        self._theme_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._theme_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for key, label in _ThemeSelector.OPTIONS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._theme_list.addItem(item)
        self._theme_list.setFixedHeight(len(_ThemeSelector.OPTIONS) * 32 + 4)
        self._theme_list.itemClicked.connect(self._on_theme_select)
        p_layout.addWidget(self._theme_list)

        self._theme_panel.adjustSize()
        self._theme_panel.hide()
        self._theme_selector.attach_panel(self._theme_panel)

    # ── Theme panel callbacks ─────────────────────────────────────────────────

    def _on_theme_select(self, item: QListWidgetItem):
        self._theme_selector.set_value(item.data(Qt.ItemDataRole.UserRole))
        self._theme_panel.hide()

    def eventFilter(self, obj, event):
        """Dismiss the floating panel when clicking outside it."""
        if (self._theme_panel.isVisible()
                and event.type() == QEvent.Type.MouseButtonPress
                and isinstance(event, QMouseEvent)):
            click = event.globalPosition().toPoint()
            panel_rect = QRect(self._theme_panel.mapToGlobal(QPoint(0, 0)),
                               self._theme_panel.size())
            btn_rect = QRect(self._theme_selector.mapToGlobal(QPoint(0, 0)),
                             self._theme_selector.size())
            if not panel_rect.contains(click) and not btn_rect.contains(click):
                self._theme_panel.hide()
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    # ── Other actions ─────────────────────────────────────────────────────────

    def _browse_download_dir(self):
        current = self._download_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select Download Folder", current)
        if path:
            self._download_edit.setText(path)

    def _add_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Watch Directory", str(Path.home()))
        if path and path not in self._dirs:
            self._dirs.append(path)
            self._list_widget.addItem(QListWidgetItem(path))

    def _remove_selected(self):
        for item in self._list_widget.selectedItems():
            self._dirs.remove(item.text())
            self._list_widget.takeItem(self._list_widget.row(item))

    def selected_theme(self) -> str:
        return self._theme_selector.value()

    def selected_download_dir(self) -> str:
        path = self._download_edit.text().strip()
        if path:
            return path
        return str(Path.home() / "Downloads" / "NovaPlay")

    def selected_watch_dirs(self) -> list[str]:
        return list(self._dirs)
