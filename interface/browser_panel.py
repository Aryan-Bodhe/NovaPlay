from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QLabel, QFrame, QMenu, QSizePolicy
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage,
    QWebEngineScript, QWebEngineSettings,
)
from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor

from models.app_settings import Bookmark
from utils.logger import get_logger

log = get_logger("browser")

HOME_URL = "https://www.google.com"


class _CustomPage(QWebEnginePage):
    new_window_requested = pyqtSignal(object)  # emits QWebEngineView
    magnet_requested     = pyqtSignal(str)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        if url.scheme() == "magnet":
            log.info("Magnet intercepted: %s", url.toString()[:80])
            self.magnet_requested.emit(url.toString())
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, window_type):
        """Handle target=_blank links and window.open() calls by emitting a signal."""
        new_view = QWebEngineView()
        new_page = _CustomPage(new_view)
        # Propagate further popup and magnet requests through the new page
        new_page.new_window_requested.connect(self.new_window_requested)
        new_page.magnet_requested.connect(self.magnet_requested)
        new_view.setPage(new_page)
        self.new_window_requested.emit(new_view)
        return new_page


class BrowserPanel(QWidget):
    """Embedded browser with address bar, bookmarks bar, and libtorrent integration."""

    title_changed   = pyqtSignal(str)
    open_in_new_tab = pyqtSignal(object)  # emits QWebEngineView
    magnet_requested = pyqtSignal(str)    # emits magnet URI

    def __init__(
        self,
        bookmarks: list[Bookmark],
        settings_manager,
        adopt_view: QWebEngineView | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._bookmarks: list[Bookmark] = list(bookmarks)
        self._settings_manager = settings_manager
        self._adopt_view = adopt_view

        self._build_ui()
        self._setup_dark_mode()

    # ── Build ─────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Navigation bar ────────────────────────────────────────
        nav = QWidget()
        nav.setFixedHeight(44)
        nav.setStyleSheet("background:#1a1a2e;border-bottom:1px solid #2a2a45;")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(8, 4, 8, 4)
        nav_layout.setSpacing(4)

        def _icon_btn(text, tip):
            b = QPushButton(text)
            b.setObjectName("icon_btn")
            b.setFixedSize(30, 30)
            b.setToolTip(tip)
            return b

        self._back_btn    = _icon_btn("◀", "Back")
        self._fwd_btn     = _icon_btn("▶", "Forward")
        self._refresh_btn = _icon_btn("↻", "Refresh")
        self._home_btn    = _icon_btn("⌂", "Home")

        self._back_btn.clicked.connect(lambda: self._browser.back())
        self._fwd_btn.clicked.connect(lambda: self._browser.forward())
        self._refresh_btn.clicked.connect(lambda: self._browser.reload())
        self._home_btn.clicked.connect(self._go_home)

        self._addr_bar = QLineEdit()
        self._addr_bar.setPlaceholderText("Enter URL or search…")
        self._addr_bar.returnPressed.connect(self._navigate_to_address)
        self._addr_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._bm_btn = QPushButton("☆")
        self._bm_btn.setObjectName("icon_btn")
        self._bm_btn.setFixedSize(30, 30)
        self._bm_btn.setToolTip("Bookmark this page")
        self._bm_btn.clicked.connect(self._toggle_bookmark)

        nav_layout.addWidget(self._back_btn)
        nav_layout.addWidget(self._fwd_btn)
        nav_layout.addWidget(self._refresh_btn)
        nav_layout.addWidget(self._home_btn)
        nav_layout.addWidget(self._addr_bar)
        nav_layout.addWidget(self._bm_btn)
        root.addWidget(nav)

        # ── Bookmarks bar (Chrome-style, below URL) ───────────────
        self._bm_bar = QFrame()
        self._bm_bar.setObjectName("bm_bar")
        self._bm_bar.setFixedHeight(30)
        self._bm_bar.setStyleSheet(
            "QFrame#bm_bar{background:#161628;border-bottom:1px solid #2a2a45;}"
        )
        self._bm_bar_layout = QHBoxLayout(self._bm_bar)
        self._bm_bar_layout.setContentsMargins(6, 2, 6, 2)
        self._bm_bar_layout.setSpacing(2)
        self._bm_bar_layout.addStretch()
        root.addWidget(self._bm_bar)
        self._rebuild_bm_bar()

        # ── Browser view ──────────────────────────────────────────
        if self._adopt_view is not None:
            self._browser = self._adopt_view
            # Page was already set up as _CustomPage by createWindow; just wire signals
            self._browser.page().new_window_requested.connect(self.open_in_new_tab)
            self._browser.page().magnet_requested.connect(self.magnet_requested)
        else:
            self._browser = QWebEngineView()
            page = _CustomPage(self._browser)
            page.new_window_requested.connect(self.open_in_new_tab)
            page.magnet_requested.connect(self.magnet_requested)
            self._browser.setPage(page)
            self._browser.load(QUrl(HOME_URL))

        self._browser.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._browser.urlChanged.connect(self._on_url_changed)
        self._browser.titleChanged.connect(self._on_title_changed)
        root.addWidget(self._browser, stretch=1)

        # ── Status strip ──────────────────────────────────────────
        self._status = QLabel("")
        self._status.setObjectName("subtitle")
        self._status.setFixedHeight(20)
        self._status.setStyleSheet(
            "background:#1a1a2e;padding:0 8px;border-top:1px solid #2a2a45;"
        )
        root.addWidget(self._status)

    def _setup_dark_mode(self):
        profile = QWebEngineProfile.defaultProfile()

        # Force OS-level dark preference (Qt 6.7+; silently skipped on older builds)
        try:
            profile.settings().setAttribute(
                QWebEngineSettings.WebAttribute.ForceDarkMode, True
            )
        except AttributeError:
            pass

        # Inject `color-scheme: dark` into every page so sites that honour the
        # media query switch to their own dark theme automatically.
        script_name = "novaplay-dark-mode"
        if profile.scripts().find(script_name) is None:
            script = QWebEngineScript()
            script.setName(script_name)
            script.setSourceCode(
                "(function(){"
                "var s=document.createElement('style');"
                "s.textContent=':root{color-scheme:dark;}';"
                "if(document.head){document.head.appendChild(s);}"
                "else{document.addEventListener('DOMContentLoaded',"
                "function(){document.head.appendChild(s);});}"
                "})();"
            )
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setRunsOnSubFrames(True)
            script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
            profile.scripts().insert(script)

        # Dark background shown before page content paints
        self._browser.page().setBackgroundColor(QColor(26, 26, 46))

    # ── Bookmarks bar ─────────────────────────────────────────────

    def _rebuild_bm_bar(self):
        lay = self._bm_bar_layout
        # Remove all widgets, keep the trailing stretch
        while lay.count() > 1:
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, bm in enumerate(self._bookmarks):
            btn = QPushButton(bm.title[:28])
            btn.setObjectName("bm_bar_btn")
            btn.setFixedHeight(24)
            btn.setToolTip(bm.url)
            btn.setStyleSheet(
                "QPushButton#bm_bar_btn{"
                "background:transparent;border:none;color:#c8c8e8;"
                "font-size:12px;padding:0 6px;border-radius:4px;}"
                "QPushButton#bm_bar_btn:hover{background:#2a2a45;color:#e0e0f0;}"
            )
            btn.clicked.connect(lambda _, u=bm.url: self._browser.load(QUrl(u)))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _, idx=i, b=btn: self._bm_context_menu(idx, b)
            )
            lay.insertWidget(lay.count() - 1, btn)

    def _bm_context_menu(self, idx: int, btn: QPushButton):
        menu = QMenu(self)
        delete_action = menu.addAction("Remove bookmark")
        action = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if action == delete_action:
            self._delete_bookmark(idx)

    def _toggle_bookmark(self):
        url = self._browser.url().toString()
        idx = next((i for i, b in enumerate(self._bookmarks) if b.url == url), -1)
        if idx >= 0:
            self._delete_bookmark(idx)
        else:
            self._add_bookmark()

    # ── Navigation ────────────────────────────────────────────────

    def navigate(self, url: str):
        self._browser.load(QUrl(url))

    def _navigate_to_address(self):
        text = self._addr_bar.text().strip()
        if not text:
            return
        if text.startswith("magnet:"):
            self.magnet_requested.emit(text)
            return
        if "." in text and " " not in text and not text.startswith("http"):
            text = "https://" + text
        elif not text.startswith(("http://", "https://", "ftp://")):
            text = f"https://www.google.com/search?q={text.replace(' ', '+')}"
        self._browser.load(QUrl(text))

    def _go_home(self):
        self._browser.load(QUrl(HOME_URL))

    def _on_url_changed(self, url: QUrl):
        self._addr_bar.setText(url.toString())
        is_bm = any(b.url == url.toString() for b in self._bookmarks)
        self._bm_btn.setText("★" if is_bm else "☆")

    def _on_title_changed(self, title: str):
        self._status.setText(title[:120] if title else "")
        self.title_changed.emit(title or "New Tab")

    # ── Bookmarks CRUD ────────────────────────────────────────────

    def set_bookmarks(self, bookmarks: list[Bookmark]):
        self._bookmarks = list(bookmarks)
        self._rebuild_bm_bar()

    def _add_bookmark(self):
        url = self._browser.url().toString()
        title = self._browser.title() or url
        if any(b.url == url for b in self._bookmarks):
            return
        self._bookmarks.append(Bookmark(title=title, url=url))
        self._save_bookmarks()
        self._bm_btn.setText("★")
        self._rebuild_bm_bar()
        log.info("Bookmark added: %s", title[:60])

    def _delete_bookmark(self, idx: int):
        if 0 <= idx < len(self._bookmarks):
            self._bookmarks.pop(idx)
            self._save_bookmarks()
            self._rebuild_bm_bar()
            url = self._browser.url().toString()
            is_bm = any(b.url == url for b in self._bookmarks)
            self._bm_btn.setText("★" if is_bm else "☆")

    def _save_bookmarks(self):
        try:
            settings = self._settings_manager.load()
            settings.bookmarks = self._bookmarks
            self._settings_manager.save(settings)
        except Exception:
            log.exception("Failed to save bookmarks")
