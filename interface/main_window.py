from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget, QStackedWidget,
    QStatusBar, QSplitter, QFrame, QPushButton, QGridLayout,
    QApplication, QLabel, QTabBar,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSlot, QSize
from PyQt6.QtGui import QKeySequence, QShortcut, QFont
from PyQt6.QtWebEngineCore import QWebEngineProfile

from config.config import SETTINGS_FILE
from models.settings_manager import SettingsManager
from interface.file_explorer import FileExplorerPanel
from interface.player_widget import PlayerWidget
from interface.browser_panel import BrowserPanel
from interface.downloads_panel import DownloadsPanel
from interface.settings_dialog import SettingsDialog
from interface.styles import get_theme
from interface.icon_store import (
    settings_icon,
    menu_icon,
    download_icon,
    ICON_SIZE_LARGE,
    ICON_SIZE_MEDIUM,
    ICON_SIZE_TINY,
    novaplay_icon,
    cross_icon,
    plus_icon,
)
from core.torrent_engine import TorrentEngine
from utils.adblocker import AdBlocker
from utils.logger import get_logger

log = get_logger("main_window")

PLAYER_TAB_LABEL = "  ▶  Player  "
_MAX_PLAYER_TAB_TITLE = 26

_ACTIVITY_BAR_W = 44    # permanent left strip width (px)
_PANEL_W        = 256   # expanded sidebar panel width (px)

class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NovaPlay")
        self.setMinimumSize(1100, 680)
        self.resize(1400, 850)

        self._settings_mgr = SettingsManager(SETTINGS_FILE)
        self._settings     = self._settings_mgr.load()
        self._settings_dialog: SettingsDialog | None = None
        self._last_active_player: PlayerWidget | None = None
        self._hovered_tab_index: int = -1
        self._tab_close_icon = cross_icon
        self._panel_visible: bool = True   # whether the side panel is expanded
        self._plus_tab_widget: QWidget | None = None
        self._plus_tab_btn: QPushButton | None = None

        # Engine lives for the full app lifetime
        self._engine = TorrentEngine(save_path=self._settings.download_dir)

        # Ad blocker – attach to the default profile before any browser view is created
        self._adblocker = AdBlocker(parent=self)
        self._adblocker.attach(QWebEngineProfile.defaultProfile())
        if self._settings.adblocker_enabled:
            self._adblocker.load_lists()

        self._build_ui()
        self._connect_signals()
        self._apply_settings()
        QApplication.instance().installEventFilter(self)
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
            b.setIconSize(ICON_SIZE_LARGE)
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
        self._settings_btn.clicked.connect(self._open_settings_dialog)
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
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.tabBarClicked.connect(self._on_tab_bar_clicked)
        self._tabs.tabBar().setMouseTracking(True)
        self._tabs.tabBar().installEventFilter(self)

        self._tabs_surface = QStackedWidget()
        self._tabs_surface.addWidget(self._tabs)
        self._tabs_surface.addWidget(self._make_tabs_blank_slate())
        self._splitter.addWidget(self._tabs_surface)
        self._splitter.setStretchFactor(1, 1)

        # Keyboard shortcuts
        # Ctrl+B / Ctrl+T work window-wide
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(
            lambda: self._toggle_panel(0)
        )
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(
            self._new_browser_tab
        )
        # Ctrl+W / Ctrl+R are handled in eventFilter so they work even when
        # focus is inside the QWebEngineView native window.

        self._ensure_plus_tab()

        player = self._create_player_tab(make_current=True)
        self._last_active_player = player
        self._new_browser_tab(make_current=False)
        self._update_tabs_surface()

        # Apply saved sidebar width
        saved_w = max(120, self._settings.sidebar_width)
        self._splitter.setSizes([saved_w, self.width() - _ACTIVITY_BAR_W - saved_w])

    def _make_tabs_blank_slate(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#000000;")

        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # ── Centered content ──────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.setSpacing(16)

        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setPixmap(novaplay_icon.pixmap(QSize(160, 160)))
        content_layout.addWidget(logo_lbl)

        name_lbl = QLabel("NovaPlay")
        font = QFont()
        font.setPointSize(32)
        font.setWeight(QFont.Weight.Thin)
        name_lbl.setFont(font)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("color:#c8c0e8;background:transparent;letter-spacing:6px;")
        content_layout.addWidget(name_lbl)

        hint_lbl = QLabel("Open a file from the library or press Ctrl+T for a browser tab")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setStyleSheet("color:#3a3a5a;font-size:13px;background:transparent;")
        content_layout.addWidget(hint_lbl)

        grid.addWidget(content, 0, 0, Qt.AlignmentFlag.AlignCenter)

        # ── Floating "New Tab" button – top-right corner ──────────────────────
        new_tab_btn = QPushButton("  New Tab")
        new_tab_btn.setObjectName("blank_new_tab_btn")
        new_tab_btn.setIcon(plus_icon)
        new_tab_btn.setIconSize(ICON_SIZE_MEDIUM)
        new_tab_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        new_tab_btn.setToolTip("Open a new browser tab (Ctrl+T)")
        new_tab_btn.clicked.connect(lambda: self._new_browser_tab(make_current=True))

        # Wrap in a transparent container to apply top-right margin cleanly
        btn_wrap = QWidget()
        btn_wrap.setStyleSheet("background:transparent;")
        btn_wrap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        wrap_layout = QHBoxLayout(btn_wrap)
        wrap_layout.setContentsMargins(0, 12, 12, 0)
        wrap_layout.addWidget(new_tab_btn)

        grid.addWidget(
            btn_wrap, 0, 0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        return w

    def _update_tabs_surface(self) -> None:
        has_tabs = self._content_tab_count() > 0
        self._tabs_surface.setCurrentIndex(0 if has_tabs else 1)

    def _plus_tab_index(self) -> int:
        if self._plus_tab_widget is None:
            return -1
        return self._tabs.indexOf(self._plus_tab_widget)

    def _is_plus_tab_index(self, idx: int) -> bool:
        return idx != -1 and idx == self._plus_tab_index()

    def _content_tab_count(self) -> int:
        total = self._tabs.count()
        return total - 1 if self._plus_tab_index() != -1 else total

    def _last_content_tab_index(self) -> int:
        plus_idx = self._plus_tab_index()
        last_idx = self._tabs.count() - 1
        if plus_idx == last_idx:
            return last_idx - 1
        return last_idx

    def _ensure_plus_tab(self) -> None:
        if self._plus_tab_widget is not None and self._tabs.indexOf(self._plus_tab_widget) != -1:
            return
        self._plus_tab_widget = QWidget()
        self._plus_tab_widget.setMaximumWidth(0)
        plus_idx = self._tabs.addTab(self._plus_tab_widget, "")
        self._tabs.setTabToolTip(plus_idx, "New Tab (Ctrl+T)")

        tab_bar = self._tabs.tabBar()
        btn = QPushButton(tab_bar)
        btn.setObjectName("new_tab_btn")
        btn.setIcon(plus_icon)
        btn.setIconSize(ICON_SIZE_MEDIUM)
        btn.setFixedSize(28, 28)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip("New Tab (Ctrl+T)")
        btn.clicked.connect(lambda: self._new_browser_tab(make_current=True))
        self._plus_tab_btn = btn
        tab_bar.setTabButton(plus_idx, QTabBar.ButtonPosition.LeftSide, btn)

    def _close_tab_for_widget(self, tab_widget: QWidget) -> None:
        idx = self._tabs.indexOf(tab_widget)
        if idx != -1:
            self._close_tab(idx)

    def _sync_tab_close_button_visibility(self) -> None:
        current_idx = self._tabs.currentIndex()
        tab_bar = self._tabs.tabBar()
        for idx in range(self._tabs.count()):
            if self._is_plus_tab_index(idx):
                continue
            btn = tab_bar.tabButton(idx, QTabBar.ButtonPosition.RightSide)
            if btn is None:
                continue
            btn.setVisible(idx == current_idx or idx == self._hovered_tab_index)

    def _refresh_tab_close_buttons(self) -> None:
        tab_bar = self._tabs.tabBar()
        for idx in range(self._tabs.count()):
            if self._is_plus_tab_index(idx):
                tab_bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, None)
                if (self._plus_tab_btn is not None
                        and tab_bar.tabButton(idx, QTabBar.ButtonPosition.LeftSide)
                            is not self._plus_tab_btn):
                    tab_bar.setTabButton(
                        idx, QTabBar.ButtonPosition.LeftSide, self._plus_tab_btn
                    )
                continue
            tab_widget = self._tabs.widget(idx)
            close_btn = QPushButton(tab_bar)
            close_btn.setObjectName("icon_btn")
            close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_btn.setToolTip("Close Tab")
            close_btn.setIcon(self._tab_close_icon)
            close_btn.setIconSize(ICON_SIZE_TINY)
            close_btn.setFixedSize(16, 16)
            close_btn.clicked.connect(
                lambda _checked=False, w=tab_widget: self._close_tab_for_widget(w)
            )
            tab_bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, close_btn)
        self._sync_tab_close_button_visibility()

    def _player_indices(self) -> list[int]:
        indices: list[int] = []
        tab_count = self._tabs.count()
        for i in range(tab_count):
            if isinstance(self._tabs.widget(i), PlayerWidget):
                indices.append(i)
        return indices

    def _player_insert_index(self) -> int:
        tab_count = self._tabs.count()
        plus_idx = self._plus_tab_index()
        for i in range(tab_count):
            widget = self._tabs.widget(i)
            if isinstance(widget, BrowserPanel):
                return i
        return plus_idx if plus_idx != -1 else tab_count

    def _browser_insert_index(self) -> int:
        plus_idx = self._plus_tab_index()
        return plus_idx if plus_idx != -1 else self._tabs.count()

    def _format_player_tab_text(self, title: str) -> str:
        if not title:
            return PLAYER_TAB_LABEL
        if len(title) > _MAX_PLAYER_TAB_TITLE:
            title = title[:_MAX_PLAYER_TAB_TITLE - 1] + "…"
        return f"  ▶  {title}  "

    def _create_player_tab(self, title: str | None = None, make_current: bool = True) -> PlayerWidget:
        player = PlayerWidget(volume=self._settings.last_volume)
        insert_idx = self._player_insert_index()
        tab_text = self._format_player_tab_text(title or "Player")
        self._tabs.insertTab(insert_idx, player, tab_text)
        self._refresh_tab_close_buttons()
        self._update_tabs_surface()
        if make_current:
            self._tabs.setCurrentIndex(insert_idx)
        return player

    def _first_existing_player(self) -> PlayerWidget | None:
        for idx in self._player_indices():
            widget = self._tabs.widget(idx)
            if isinstance(widget, PlayerWidget):
                return widget
        return None

    def _pick_player_for_play(self) -> PlayerWidget:
        current = self._tabs.currentWidget()
        if isinstance(current, PlayerWidget):
            return current

        if self._last_active_player is not None:
            try:
                if self._tabs.indexOf(self._last_active_player) != -1:
                    return self._last_active_player
            except RuntimeError:
                self._last_active_player = None

        existing = self._first_existing_player()
        if existing is not None:
            return existing

        return self._create_player_tab(make_current=False)

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
        if idx < 0:
            return
        if self._is_plus_tab_index(idx):
            fallback_idx = self._last_content_tab_index()
            if fallback_idx >= 0:
                self._tabs.setCurrentIndex(fallback_idx)
            return
        current = self._tabs.widget(idx)
        if isinstance(current, PlayerWidget):
            self._last_active_player = current
        if current is not None:
            current.setFocus()
        self._sync_tab_close_button_visibility()

    def _on_tab_bar_clicked(self, idx: int) -> None:
        if self._is_plus_tab_index(idx):
            self._new_browser_tab(make_current=True)

    def _new_browser_tab(self, make_current: bool = True) -> None:
        settings = self._settings_mgr.load()
        browser  = BrowserPanel(
            bookmarks=settings.bookmarks,
            settings_manager=self._settings_mgr,
            adblocker=self._adblocker,
        )
        self._wire_browser(browser)

        insert_idx = self._browser_insert_index()
        self._tabs.insertTab(insert_idx, browser, "  🌐  New Tab  ")
        browser.title_changed.connect(
            lambda title, b=browser: self._tabs.setTabText(
                self._tabs.indexOf(b),
                f"  {title[:22]}  " if title else "  New Tab  "
            )
        )
        if make_current:
            self._tabs.setCurrentIndex(insert_idx)
        self._refresh_tab_close_buttons()
        self._update_tabs_surface()
        log.debug("Opened browser tab at index %d", insert_idx)

    def _adopt_tab_view(self, view) -> None:
        """Called when a page opens a popup / target=_blank link."""
        settings = self._settings_mgr.load()
        browser  = BrowserPanel(
            bookmarks=settings.bookmarks,
            settings_manager=self._settings_mgr,
            adblocker=self._adblocker,
            adopt_view=view,
        )
        self._wire_browser(browser)

        insert_idx = self._browser_insert_index()
        self._tabs.insertTab(insert_idx, browser, "  🌐  New Tab  ")
        browser.title_changed.connect(
            lambda title, b=browser: self._tabs.setTabText(
                self._tabs.indexOf(b),
                f"  {title[:22]}  " if title else "  New Tab  "
            )
        )
        self._tabs.setCurrentIndex(insert_idx)
        self._refresh_tab_close_buttons()
        self._update_tabs_surface()
        log.debug("Adopted popup tab at index %d", insert_idx)

    def _wire_browser(self, browser: BrowserPanel) -> None:
        """Connect all signals from a newly created BrowserPanel."""
        browser.open_in_new_tab.connect(self._adopt_tab_view)
        browser.magnet_requested.connect(self._on_magnet_requested)

    def _close_tab(self, index: int | None = None) -> None:
        if index is None:
            index = self._tabs.currentIndex()

        if index < 0 or index >= self._tabs.count():
            return
        if self._is_plus_tab_index(index):
            return

        widget = self._tabs.widget(index)
        if isinstance(widget, PlayerWidget):
            widget.stop()
        self._tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

        if widget is self._last_active_player:
            self._last_active_player = None

        self._hovered_tab_index = -1
        self._refresh_tab_close_buttons()
        self._update_tabs_surface()

        if self._content_tab_count() > 0:
            target = max(0, min(index, self._last_content_tab_index()))
            self._tabs.setCurrentIndex(target)

        log.debug("Closed tab at index %d", index)

    def _refresh_current_tab(self) -> None:
        index = self._tabs.currentIndex()
        if index < 0 or index >= self._tabs.count():
            return
        widget = self._tabs.widget(index)
        if isinstance(widget, BrowserPanel):
            widget.reload()

    def _cycle_tab(self, direction: int) -> None:
        """Switch to the next (direction=+1) or previous (direction=-1) content tab, cycling."""
        content_indices = [
            i for i in range(self._tabs.count())
            if not self._is_plus_tab_index(i)
        ]
        if len(content_indices) <= 1:
            return
        try:
            pos = content_indices.index(self._tabs.currentIndex())
        except ValueError:
            pos = 0
        self._tabs.setCurrentIndex(
            content_indices[(pos + direction) % len(content_indices)]
        )

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

    def _open_settings_dialog(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return

        current = self._settings_mgr.load()
        dlg = SettingsDialog(
            theme=current.theme,
            download_dir=current.download_dir,
            watch_dirs=current.watch_dirs,
            adblocker_enabled=current.adblocker_enabled,
            parent=self,
        )
        self._settings_dialog = dlg
        dlg.finished.connect(self._finish_settings_dialog)
        dlg.open()
        dlg.raise_()
        dlg.activateWindow()

    def _finish_settings_dialog(self, result: int) -> None:
        dlg = self._settings_dialog
        self._settings_dialog = None
        if dlg is None:
            return

        if result != dlg.DialogCode.Accepted:
            dlg.deleteLater()
            return

        new_theme             = dlg.selected_theme()
        new_download_dir      = dlg.selected_download_dir()
        new_watch_dirs        = dlg.selected_watch_dirs()
        new_adblocker_enabled = dlg.selected_adblocker_enabled()

        settings = self._settings_mgr.load()
        theme_changed             = settings.theme != new_theme
        download_dir_changed      = settings.download_dir != new_download_dir
        watch_dirs_changed        = settings.watch_dirs != new_watch_dirs
        adblocker_changed         = settings.adblocker_enabled != new_adblocker_enabled

        settings.theme             = new_theme
        settings.download_dir      = new_download_dir
        settings.watch_dirs        = new_watch_dirs
        settings.adblocker_enabled = new_adblocker_enabled
        self._settings_mgr.save(settings)
        self._settings = settings

        if theme_changed:
            QApplication.instance().setStyleSheet(get_theme(new_theme))
            self._statusbar.showMessage(f"Theme: {new_theme}", 2500)

        if download_dir_changed:
            self._engine.set_save_path(new_download_dir)
            self._downloads_panel.refresh()
            self._statusbar.showMessage(f"Download folder: {new_download_dir}", 3000)

        if watch_dirs_changed:
            self._explorer.set_watch_dirs(new_watch_dirs)
            self._statusbar.showMessage("Watch directories updated", 2500)

        if adblocker_changed:
            self._adblocker.enabled = new_adblocker_enabled
            if new_adblocker_enabled:
                self._adblocker.load_lists()
            self._statusbar.showMessage(
                f"Ad blocker {'enabled' if new_adblocker_enabled else 'disabled'}", 2500
            )

        dlg.deleteLater()

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
        player = self._pick_player_for_play()
        player_idx = self._tabs.indexOf(player)
        if player_idx != -1:
            self._tabs.setCurrentIndex(player_idx)
            self._tabs.setTabText(player_idx, self._format_player_tab_text(path.name))
        player.play(path)
        player.setFocus()
        self._last_active_player = player
        self._statusbar.showMessage(f"Playing: {path.name}", 5000)

    @pyqtSlot(list)
    def _on_dirs_changed(self, dirs: list[str]) -> None:
        settings           = self._settings_mgr.load()
        settings.watch_dirs = dirs
        self._settings_mgr.save(settings)

    # ── Global key intercept ───────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        """Route player keyboard shortcuts regardless of which widget has focus."""
        tab_bar = self._tabs.tabBar()
        if obj is tab_bar:
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                hovered = tab_bar.tabAt(pos)
                if hovered != self._hovered_tab_index:
                    self._hovered_tab_index = hovered
                    self._sync_tab_close_button_visibility()
            elif event.type() == QEvent.Type.Leave:
                if self._hovered_tab_index != -1:
                    self._hovered_tab_index = -1
                    self._sync_tab_close_button_visibility()
            return False

        if QApplication.activeModalWidget() is not None:
            return False

        if event.type() == QEvent.Type.KeyPress:
            mods = event.modifiers()
            k    = event.key()

            # Tab shortcuts – handled here so they fire even when
            # QWebEngineView's native window has keyboard focus.
            if mods == Qt.KeyboardModifier.ControlModifier:
                if k == Qt.Key.Key_W:
                    self._close_tab()
                    return True
                if k == Qt.Key.Key_R:
                    self._refresh_current_tab()
                    return True
                if k == Qt.Key.Key_Tab:
                    self._cycle_tab(+1)
                    return True

            _ctrl_shift = (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
            )
            if mods == _ctrl_shift and k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self._cycle_tab(-1)
                return True

            current = self._tabs.currentWidget()
            if isinstance(current, PlayerWidget):
                k = event.key()
                mods = event.modifiers()
                if mods == Qt.KeyboardModifier.NoModifier:
                    player_keys = (
                        Qt.Key.Key_Space, Qt.Key.Key_Left, Qt.Key.Key_Right,
                        Qt.Key.Key_F, Qt.Key.Key_F11, Qt.Key.Key_M,
                    )
                    if k in player_keys or (
                        k == Qt.Key.Key_Escape and current._is_fullscreen
                    ):
                        if current._is_fullscreen and current._fullscreen_win:
                            current._fullscreen_win.keyPressEvent(event)
                        else:
                            current.keyPressEvent(event)
                        return True
        return False

    # ── Close ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        self._tabs.tabBar().removeEventFilter(self)
        try:
            sizes                  = self._splitter.sizes()
            settings               = self._settings_mgr.load()
            first_player = self._first_existing_player()
            if first_player is not None:
                settings.last_volume = first_player.get_volume()
            settings.sidebar_width = sizes[0] if sizes else _PANEL_W
            self._settings_mgr.save(settings)
        except Exception:
            log.exception("Failed to save settings on exit")

        for idx in self._player_indices():
            widget = self._tabs.widget(idx)
            if isinstance(widget, PlayerWidget):
                widget.stop()

        self._engine.shutdown()
        log.info("NovaPlay exiting")
        super().closeEvent(event)
