import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView  # must import early on some platforms

from interface.main_window import MainWindow
from interface.styles import PURPLE_THEME
from interface.icon_store import novaplay_logo

def main():
    app = QApplication(sys.argv)

    app.setApplicationName("NovaPlay")
    app.setOrganizationName("NovaPlay")
    # Helps Linux desktop environments map app windows to .desktop launchers.
    app.setDesktopFileName("novaplay")
    app.setStyleSheet(PURPLE_THEME)
    app.setWindowIcon(novaplay_logo)

    window = MainWindow()
    window.setWindowIcon(novaplay_logo)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
