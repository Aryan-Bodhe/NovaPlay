from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget, QStackedWidget,
    QStatusBar, QSplitter, QFrame, QPushButton, QMenu,
    QApplication, QTabBar,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence, QShortcut

from config.config import SETTINGS_FILE
from models.settings_manager import SettingsManager
from interface.file_explorer import FileExplorerPanel
from interface.player_widget import PlayerWidget
from interface.browser_panel import BrowserPanel
from interface.downloads_panel import DownloadsPanel
from interface.styles import get_theme
from interface.icon_store import settings_icon, menu_icon, download_icon, ICON_SIZE
from core.torrent_engine import TorrentEngine
from utils.logger import get_logger

log = get_logger("main_window")

PLAYER_TAB_INDEX = 0
PLAYER_TAB_LABEL = "  ▶  Player  "

_ACTIVITY_BAR_W = 44    # permanent left strip width (px)
_PANEL_W        = 256   # expanded sidebar panel width (px)

# QSS patch applied specifically to the main tab widget so the "+" tab
# always appears as a compact square button right beside the real tabs.
_PLUS_TAB_QSS = """
QTabBar::tab:last {
    min-width : 28px;
    max-width : 28px;
    padding   : 4px 2px;
    color     : #9090b0;
    font-size : 16px;
    font-weight: bold;
}
QTabBar::tab:last:hover { color: #e0e0f0; background: #2a2a45; }
"""


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NovaPlay")
        self.setMinimumSize(1100, 680)
        self.resize(1400, 850)

        self._settings_mgr = SettingsManager(SETTINGS_FILE)
        self._settings     = self._settings_mgr.load()
        self._plus_tab_idx: int  = -1
        self._panel_visible: bool = True   # whether the side panel is expanded

        # Engine lives for the full app lifetime
        self._engine = TorrentEngine(save_path=self._settings.download_dir)

        self._build_ui()
        self._connect_signals()
        self._apply_settings()
        log.info("NovaPlay started")

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Status bar
        self._statusbar = QStatusBar()
        self._statusbar.showMessage("Ready")
        self.setStatusBar(self._statusbar)

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Activity bar (permanent left strip) ───────────────────────────────
        activity_bar = QFrame()
        activity_bar.setObjectName("activity_bar")
        activity_bar.setFixedWidth(_ACTIVITY_BAR_W)

        ab_layout = QVBoxLayout(activity_bar)
        ab_layout.setContentsMargins(0, 8, 0, 8)
        ab_layout.setSpacing(4)

        def _ab_btn(icon, tip):
            b = QPushButton()
            b.setIcon(icon)
            b.setIconSize(ICON_SIZE)
            b.setObjectName("icon_btn")
            b.setFixedSize(32, 32)
            b.setToolTip(tip)
            return b

        self._hamburger_btn  = _ab_btn(menu_icon,      "Library (Ctrl+B)")
        self._downloads_btn  = _ab_btn(download_icon,  "Downloads")

        ab_layout.addWidget(
            self._hamburger_btn,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
        )
        ab_layout.addWidget(
            self._downloads_btn,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
        )
        ab_layout.addStretch()

        self._settings_btn = _ab_btn(settings_icon, "Settings")
        self._settings_btn.clicked.connect(self._show_settings_menu)
        ab_layout.addWidget(
            self._settings_btn,
            alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        )

        main_layout.addWidget(activity_bar)

        # ── Splitter: [panel stack | tabs] ────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        main_layout.addWidget(self._splitter)

        # Panel stack (slot 0) – switches between Library and Downloads
        self._panel_stack = QStackedWidget()
        self._splitter.addWidget(self._panel_stack)
        self._splitter.setStretchFactor(0, 0)

        self._explorer = FileExplorerPanel(
            watch_dirs=self._settings.watch_dirs,
            settings_manager=self._settings_mgr,
        )
        self._panel_stack.addWidget(self._explorer)          # index 0

        self._downloads_panel = DownloadsPanel(self._engine)
        self._panel_stack.addWidget(self._downloads_panel)   # index 1

        self._panel_stack.setCurrentIndex(0)

        # Wire activity-bar buttons
        self._hamburger_btn.clicked.connect(lambda: self._toggle_panel(0))
        self._downloads_btn.clicked.connect(lambda: self._toggle_panel(1))

        # Tab widget (slot 1)
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._tabs.setDocumentMode(True)
        self._tabs.setTabsClosable(True)
        self._tabs.setStyleSheet(_PLUS_TAB_QSS)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._splitter.addWidget(self._tabs)
        self._splitter.setStretchFactor(1, 1)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(
            lambda: self._toggle_panel(0)
        )
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(
            self._new_browser_tab
        )
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(
            lambda: self._close_tab
        )

        # Player tab (no close button)
        self._player = PlayerWidget(volume=self._settings.last_volume)
        self._tabs.addTab(self._player, PLAYER_TAB_LABEL)
        self._tabs.tabBar().setTabButton(
            PLAYER_TAB_INDEX, QTabBar.ButtonPosition.RightSide, None
        )

        self._new_browser_tab()
        self._add_plus_tab()
        self._tabs.setCurrentIndex(PLAYER_TAB_INDEX)

        # Apply saved sidebar width
        saved_w = max(120, self._settings.sidebar_width)
        self._splitter.setSizes([saved_w, self.width() - _ACTIVITY_BAR_W - saved_w])

    def _add_plus_tab(self) -> None:
        plus_placeholder = QWidget()
        self._plus_tab_idx = self._tabs.addTab(plus_placeholder, "+")
        self._tabs.tabBar().setTabButton(
            self._plus_tab_idx, QTabBar.ButtonPosition.RightSide, None
        )

    def _connect_signals(self) -> None:
        self._explorer.file_selected.connect(self._on_file_selected)
        self._explorer.dirs_changed.connect(self._on_dirs_changed)

    def _apply_settings(self) -> None:
        QApplication.instance().setStyleSheet(get_theme(self._settings.theme))
        log.info("Applied theme: %s", self._settings.theme)

    # ── Panel management ───────────────────────────────────────────────────────

    def _toggle_panel(self, idx: int) -> None:
        """
        idx 0 = Library (FileExplorer)
        idx 1 = Downloads

        If the panel is visible and shows the requested page: collapse it.
        If collapsed, or showing a different page: expand / switch to idx.
        """
        if self._panel_visible and self._panel_stack.currentIndex() == idx:
            self._panel_visible = False
            self._panel_stack.hide()
            self._resize_panel(0)
        else:
            was_visible = self._panel_visible
            self._panel_stack.setCurrentIndex(idx)
            self._panel_stack.show()
            self._panel_visible = True
            if not was_visible:
                self._resize_panel(_PANEL_W)
            # Refresh library tree if switching to it while it has no content
            if idx == 0 and self._explorer._model.rowCount() == 0:
                self._explorer.refresh()

    def _resize_panel(self, width: int) -> None:
        sizes = list(self._splitter.sizes())
        if len(sizes) < 2:
            return
        total    = sum(sizes)
        sizes[0] = width
        sizes[-1] = max(0, total - width)
        self._splitter.setSizes(sizes)

    # ── Tab management ─────────────────────────────────────────────────────────

    def _on_current_changed(self, idx: int) -> None:
        if idx == self._plus_tab_idx:
            self._new_browser_tab()

    def _new_browser_tab(self) -> None:
        settings = self._settings_mgr.load()
        browser  = BrowserPanel(
            bookmarks=settings.bookmarks,
            settings_manager=self._settings_mgr,
        )
        self._wire_browser(browser)

        insert_idx = max(1, self._plus_tab_idx)
        self._tabs.insertTab(insert_idx, browser, "  🌐  New Tab  ")
        browser.title_changed.connect(
            lambda title, b=browser: self._tabs.setTabText(
                self._tabs.indexOf(b),
                f"  {title[:22]}  " if title else "  New Tab  "
            )
        )
        self._plus_tab_idx += 1
        self._tabs.setCurrentIndex(insert_idx)
        log.debug("Opened browser tab at index %d", insert_idx)

    def _adopt_tab_view(self, view) -> None:
        """Called when a page opens a popup / target=_blank link."""
        settings = self._settings_mgr.load()
        browser  = BrowserPanel(
            bookmarks=settings.bookmarks,
            settings_manager=self._settings_mgr,
            adopt_view=view,
        )
        self._wire_browser(browser)

        insert_idx = max(1, self._plus_tab_idx)
        self._tabs.insertTab(insert_idx, browser, "  🌐  New Tab  ")
        browser.title_changed.connect(
            lambda title, b=browser: self._tabs.setTabText(
                self._tabs.indexOf(b),
                f"  {title[:22]}  " if title else "  New Tab  "
            )
        )
        self._plus_tab_idx += 1
        self._tabs.setCurrentIndex(insert_idx)
        log.debug("Adopted popup tab at index %d", insert_idx)

    def _wire_browser(self, browser: BrowserPanel) -> None:
        """Connect all signals from a newly created BrowserPanel."""
        browser.open_in_new_tab.connect(self._adopt_tab_view)
        browser.magnet_requested.connect(self._on_magnet_requested)

    def _close_tab(self) -> None:
        index = self._tabs.currentIndex()
        if index == PLAYER_TAB_INDEX or index == self._plus_tab_idx:
            return
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._plus_tab_idx -= 1
        self._tabs.setCurrentIndex(max(0, self._tabs.currentIndex() - 1))
        log.debug("Closed tab at index %d (+ is now %d)", index, self._plus_tab_idx)

    # ── Torrent / magnet ───────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_magnet_requested(self, uri: str) -> None:
        self._engine.add_magnet(uri, save_path=self._settings_mgr.load().download_dir)
        # Show downloads panel if it isn't already the active visible panel
        already_showing = self._panel_visible and self._panel_stack.currentIndex() == 1
        if not already_showing:
            self._toggle_panel(1)
        self._statusbar.showMessage("Magnet added to downloads", 3000)

    # ── Settings / theme ───────────────────────────────────────────────────────

    def _show_settings_menu(self) -> None:
        menu = QMenu(self)
        theme_menu   = menu.addMenu("Theme")
        theme_labels = {"purple": "Purple Dark", "vscode": "VS Code Dark"}
        current      = self._settings_mgr.load().theme

        for key, label in theme_labels.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda checked, k=key: self._set_theme(k))
            theme_menu.addAction(action)

        menu.addSeparator()
        settings   = self._settings_mgr.load()
        dl_info    = QAction(f"Downloads → {settings.download_dir}", self)
        dl_info.setEnabled(False)
        menu.addAction(dl_info)

        pos = self._settings_btn.mapToGlobal(self._settings_btn.rect().topRight())
        pos.setY(pos.y() - menu.sizeHint().height())
        menu.exec(pos)

    def _set_theme(self, name: str) -> None:
        QApplication.instance().setStyleSheet(get_theme(name))
        settings       = self._settings_mgr.load()
        settings.theme = name
        self._settings_mgr.save(settings)
        self._settings = settings
        log.info("Theme changed to: %s", name)
        self._statusbar.showMessage(f"Theme: {name}", 3000)

    # ── Slots ──────────────────────────────────────────────────────────────────

    @pyqtSlot(Path)
    def _on_file_selected(self, path: Path) -> None:
        self._tabs.setCurrentIndex(PLAYER_TAB_INDEX)
        self._player.play(path)
        self._statusbar.showMessage(f"Playing: {path.name}", 5000)

    @pyqtSlot(list)
    def _on_dirs_changed(self, dirs: list[str]) -> None:
        settings           = self._settings_mgr.load()
        settings.watch_dirs = dirs
        self._settings_mgr.save(settings)

    # ── Close ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        try:
            sizes                  = self._splitter.sizes()
            settings               = self._settings_mgr.load()
            settings.last_volume   = self._player.get_volume()
            settings.sidebar_width = sizes[0] if sizes else _PANEL_W
            self._settings_mgr.save(settings)
        except Exception:
            log.exception("Failed to save settings on exit")
        self._player.stop()
        self._engine.shutdown()
        log.info("NovaPlay exiting")
        super().closeEvent(event)
