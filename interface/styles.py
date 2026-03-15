"""
Centralised theme definitions for NovaPlay.
Each theme is a QSS string. Add new themes to THEMES dict.
"""

# ── VSCode Dark theme (default) ───────────────────────────────────────────────
_VSCODE = """
QWidget {
    background-color: #1e1e1e;
    color: #cccccc;
    font-family: "Segoe UI", "Ubuntu", "Inter", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}
QMainWindow { background-color: #1e1e1e; }

QToolBar {
    background-color: #3c3c3c;
    border-bottom: 1px solid #252526;
    padding: 2px 6px;
    spacing: 4px;
}
QMenuBar {
    background-color: #3c3c3c;
    border-bottom: 1px solid #252526;
    color: #cccccc;
}
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected { background: #505050; }

QMenu {
    background-color: #252526;
    border: 1px solid #454545;
    border-radius: 4px;
    padding: 4px;
    color: #cccccc;
}
QMenu::item { padding: 5px 22px 5px 10px; border-radius: 3px; }
QMenu::item:selected { background-color: #04395e; color: #ffffff; }
QMenu::separator { height: 1px; background: #454545; margin: 3px 8px; }

QTabWidget::pane { border: none; background: #1e1e1e; }
QTabBar { background: #252526; }
QTabBar::tab {
    background: #2d2d2d;
    color: #9d9d9d;
    padding: 7px 16px;
    border-right: 1px solid #252526;
    border-bottom: 1px solid transparent;
    min-width: 80px;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    color: #ffffff;
    border-bottom: 1px solid #1e1e1e;
}
QTabBar::tab:hover:!selected { background: #2a2d2e; color: #cccccc; }
QTabBar::close-button { subcontrol-position: right; }

QPushButton {
    background-color: #3a3d41;
    color: #cccccc;
    border: 1px solid #4a4d52;
    border-radius: 4px;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #45494e; border-color: #007acc; }
QPushButton:pressed { background-color: #007acc; color: #ffffff; border-color: #007acc; }
QPushButton:disabled { background-color: #2a2a2a; color: #555555; border-color: #3a3a3a; }
QPushButton#accent { background-color: #007acc; color: #ffffff; border: none; }
QPushButton#accent:hover { background-color: #1a8ad4; }
QPushButton#icon_btn {
    background: transparent; border: none; padding: 3px; border-radius: 3px;
}
QPushButton#icon_btn:hover { background: #3a3d41; }

QSlider::groove:horizontal {
    height: 4px; background: #464647; border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #007acc; border-radius: 2px; height: 4px;
}
QSlider::handle:horizontal {
    background: #ffffff; border: 1px solid #007acc;
    width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #007acc; }

QScrollBar:vertical {
    background: #1e1e1e; width: 8px; border-radius: 4px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #424242; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #007acc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1e1e1e; height: 8px; border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #424242; border-radius: 4px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #007acc; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QTreeView {
    background-color: #252526;
    alternate-background-color: #252526;
    border: none;
    show-decoration-selected: 1;
}
QTreeView::item { padding: 4px 6px; border-radius: 2px; }
QTreeView::item:hover { background-color: #2a2d2e; }
QTreeView::item:selected { background-color: #04395e; color: #ffffff; }
QTreeView::item:selected:hover { background-color: #094771; }

QLineEdit {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: #264f78;
}
QLineEdit:focus { border-color: #007acc; }

QComboBox {
    background-color: #3c3c3c;
    color: #cccccc;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 4px 8px;
    padding-right: 26px;
}
QComboBox:focus { border-color: #007acc; }
QComboBox:hover { border-color: #007acc; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
}
QComboBox::down-arrow {
    image: url(assets/icons/dropdown.svg);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background-color: #252526;
    color: #cccccc;
    border: 1px solid #454545;
    selection-background-color: #04395e;
    selection-color: #ffffff;
    outline: none;
}

QLabel { color: #cccccc; background: transparent; }
QLabel#title { font-size: 11px; font-weight: 600; color: #bbbbbb;
               text-transform: uppercase; letter-spacing: 1px; }
QLabel#subtitle { color: #6d6d6d; font-size: 11px; }

QSplitter::handle { background-color: #3c3c3c; width: 1px; }
QSplitter::handle:hover { background-color: #007acc; }

QListWidget {
    background-color: #252526; border: 1px solid #3c3c3c;
    border-radius: 4px; padding: 2px;
}
QListWidget::item { padding: 5px 8px; border-radius: 2px; }
QListWidget::item:selected { background-color: #04395e; }
QListWidget::item:hover { background-color: #2a2d2e; }

QDialog { background-color: #252526; border: 1px solid #454545; border-radius: 6px; }

QStatusBar {
    background-color: #007acc; color: #ffffff;
    border: none; font-size: 11px;
}

QToolTip {
    background-color: #252526; color: #cccccc;
    border: 1px solid #454545; border-radius: 3px; padding: 3px 6px;
}

QFrame#video_frame { background-color: #000000; }
QWidget#sidebar_frame { background-color: #252526; border-right: 1px solid #3c3c3c; }
QScrollArea#sidebar_scroll { border: none; background-color: #252526; }
QScrollArea#sidebar_scroll > QWidget > QWidget { background-color: #252526; }
QWidget#sidebar_content { background-color: #252526; }
QFrame#controls_bar { background-color: #007acc22; border-top: 1px solid #3c3c3c; }
QFrame#controls_bar QLabel { color: #cccccc; }
QLabel#section_header {
    font-size: 11px; font-weight: 600; color: #6d6d6d;
    padding: 6px 12px 2px;
}
"""

# ── Purple Dark theme (original) ──────────────────────────────────────────────
_PURPLE = """
QWidget {
    background-color: #0f0f17;
    color: #e0e0f0;
    font-family: "Segoe UI", "Inter", "Ubuntu", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}
QMainWindow { background-color: #0f0f17; }
QToolBar {
    background-color: #1a1a2e;
    border-bottom: 1px solid #2a2a45;
    padding: 4px 8px; spacing: 6px;
}
QMenuBar { background-color: #1a1a2e; border-bottom: 1px solid #2a2a45; }
QMenuBar::item { padding: 5px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background-color: #2d2d50; }
QMenu {
    background-color: #1e1e35; border: 1px solid #2d2d50;
    border-radius: 6px; padding: 4px;
}
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; }
QMenu::item:selected { background-color: #4a3f8f; }
QMenu::separator { height: 1px; background: #2d2d50; margin: 4px 8px; }

QTabWidget::pane { border: none; background-color: #0f0f17; }
QTabBar { background-color: #1a1a2e; }
QTabBar::tab {
    background-color: #1a1a2e; color: #9090b0;
    padding: 8px 20px; border-bottom: 2px solid transparent;
    font-weight: 500; min-width: 80px;
}
QTabBar::tab:selected { color: #c77dff; border-bottom: 2px solid #c77dff; }
QTabBar::tab:hover:!selected { color: #d0d0f0; background-color: #222240; }

QPushButton {
    background-color: #2a2a45; color: #e0e0f0;
    border: 1px solid #3a3a60; border-radius: 6px; padding: 6px 14px; font-weight: 500;
}
QPushButton:hover { background-color: #3a3a65; border-color: #7c3aed; }
QPushButton:pressed { background-color: #4a3f8f; border-color: #c77dff; }
QPushButton:disabled { background-color: #1a1a2a; color: #505070; border-color: #2a2a40; }
QPushButton#accent { background-color: #7c3aed; color: #ffffff; border: none; }
QPushButton#accent:hover { background-color: #9d55ff; }
QPushButton#icon_btn { background: transparent; border: none; padding: 4px; border-radius: 4px; }
QPushButton#icon_btn:hover { background-color: #2a2a45; }

QSlider::groove:horizontal { height: 4px; background: #2a2a45; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #7c3aed; border-radius: 2px; height: 4px; }
QSlider::handle:horizontal {
    background: #c77dff; border: 2px solid #7c3aed;
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #ffffff; border-color: #c77dff; }

QScrollBar:vertical { background: #1a1a2e; width: 8px; border-radius: 4px; margin: 0; }
QScrollBar::handle:vertical { background: #3a3a60; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #7c3aed; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #1a1a2e; height: 8px; border-radius: 4px; }
QScrollBar::handle:horizontal { background: #3a3a60; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #7c3aed; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QTreeView {
    background-color: #12121f; alternate-background-color: #14142a;
    border: none; show-decoration-selected: 1;
}
QTreeView::item { padding: 5px 4px; border-radius: 4px; }
QTreeView::item:hover { background-color: #22224a; }
QTreeView::item:selected { background-color: #3d2f7a; color: #e8e0ff; }
QTreeView::item:selected:hover { background-color: #4d3f8a; }

QLineEdit {
    background-color: #1e1e35; color: #e0e0f0;
    border: 1px solid #2d2d50; border-radius: 6px;
    padding: 5px 10px; selection-background-color: #4a3f8f;
}
QLineEdit:focus { border-color: #7c3aed; }

QComboBox {
    background-color: #1e1e35;
    color: #e0e0f0;
    border: 1px solid #2d2d50;
    border-radius: 6px;
    padding: 5px 10px;
    padding-right: 28px;
}
QComboBox:focus { border-color: #7c3aed; }
QComboBox:hover { border-color: #7c3aed; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
}
QComboBox::down-arrow {
    image: url(assets/icons/dropdown.svg);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e35;
    color: #e0e0f0;
    border: 1px solid #2d2d50;
    selection-background-color: #4a3f8f;
    selection-color: #ffffff;
    outline: none;
}

QLabel { color: #e0e0f0; background: transparent; }
QLabel#title { font-size: 15px; font-weight: 700; color: #c77dff; }
QLabel#subtitle { color: #8080aa; font-size: 11px; }

QSplitter::handle { background-color: #2a2a45; width: 2px; }
QSplitter::handle:hover { background-color: #7c3aed; }

QListWidget {
    background-color: #12121f; border: 1px solid #2a2a45;
    border-radius: 6px; padding: 4px;
}
QListWidget::item { padding: 6px 10px; border-radius: 4px; }
QListWidget::item:selected { background-color: #3d2f7a; }
QListWidget::item:hover { background-color: #22224a; }

QDialog { background-color: #1a1a2e; border: 1px solid #2d2d50; border-radius: 8px; }
QStatusBar { background-color: #1a1a2e; color: #8080aa; border-top: 1px solid #2a2a45; font-size: 11px; }
QToolTip { background-color: #2a2a45; color: #e0e0f0; border: 1px solid #4a4a70; border-radius: 4px; padding: 4px 8px; }

QFrame#video_frame { background-color: #000000; border-radius: 0; }
QWidget#sidebar_frame { background-color: #12121f; border-right: 1px solid #2a2a45; }
QScrollArea#sidebar_scroll { border: none; background-color: #12121f; }
QScrollArea#sidebar_scroll > QWidget > QWidget { background-color: #12121f; }
QWidget#sidebar_content { background-color: #12121f; }
QFrame#sidebar_header {background:#12121f;}
QFrame#controls_bar { background-color: #1a1a2e; border-top: 1px solid #2a2a45; }
QLabel#section_header {
    font-size: 11px; font-weight: 600; color: #6060a0;
    padding: 8px 12px 4px;
}
"""

# ── Public API ────────────────────────────────────────────────────────────────

THEMES: dict[str, str] = {
    "vscode": _VSCODE,
    "purple": _PURPLE,
}

# Keep old name for backwards compatibility
DARK_THEME = _VSCODE
PURPLE_THEME = _PURPLE


def get_theme(name: str) -> str:
    return THEMES.get(name, _PURPLE)
