import os
os.environ["QT_QPA_PLATFORM"] = "xcb"

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView  # must import early on some platforms

from config.app import SETTINGS_FILE
from interface.main_window import MainWindow
from interface.icon_store import novaplay_logo
from interface.styles import get_theme
from models.settings_manager import SettingsManager

def main():
    app = QApplication(sys.argv)

    app.setApplicationName("NovaPlay")
    app.setOrganizationName("NovaPlay")
    # Helps Linux desktop environments map app windows to .desktop launchers.
    app.setDesktopFileName("novaplay")

    # Bootstrap with persisted theme so startup and runtime use the same source.
    settings = SettingsManager(SETTINGS_FILE).load()
    app.setStyleSheet(get_theme(settings.theme))
    app.setWindowIcon(novaplay_logo)

    window = MainWindow()
    window.setWindowIcon(novaplay_logo)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
