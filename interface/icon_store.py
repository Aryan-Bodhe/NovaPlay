from pathlib import Path
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon

ICON_SIZE_LARGE = QSize(20, 20)
ICON_SIZE_MEDIUM = QSize(14, 14)
ICON_SIZE_SMALL = QSize(12, 12)

# Resolve icons relative to repository root so launching from any CWD works.
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

_NOVAPLAY_LOGO = _ASSETS_DIR / "NovaPlay.svg"
_NOVAPLAY_ICON = _ASSETS_DIR / "novaplay_embed.svg"
_PLAY = _ASSETS_DIR / "play.svg"
_PAUSE = _ASSETS_DIR / "pause.svg"
_STOP = _ASSETS_DIR / "stop.svg"
_MUTE = _ASSETS_DIR / "mute_cross.svg"
_VOLUME = _ASSETS_DIR / "unmute.svg"
_AUDIO = _ASSETS_DIR / "audio.svg"
_SUBTITLE = _ASSETS_DIR / "subtitles.svg"
_PLUS = _ASSETS_DIR / "plus.svg"
_BIG_PLUS = _ASSETS_DIR / "big_plus.svg"
_MINUS = _ASSETS_DIR / "minus.svg"
_FULL_SCR = _ASSETS_DIR / "fullscreen.svg"
_RESTORE_SCR = _ASSETS_DIR / "restore_screen.svg"
_NEW_FOLDER = _ASSETS_DIR / "new_folder_3.svg"
_FOLDER = _ASSETS_DIR / "folder.svg"
_MENU = _ASSETS_DIR / "menu.svg"
_REFRESH = _ASSETS_DIR / "refresh.svg"
_SETTINGS = _ASSETS_DIR / "settings.svg"
_TRASH    = _ASSETS_DIR / "trash.svg"
_DOWNLOAD = _ASSETS_DIR / "download.svg"
_PIN = _ASSETS_DIR / "pin.svg"
_PINNED = _ASSETS_DIR / "pinned.svg"
_LEFT_ARROW = _ASSETS_DIR / "left_arrow.svg"
_RIGHT_ARROW = _ASSETS_DIR / "right_arrow.svg"
_HOME = _ASSETS_DIR / "home.svg"
_STAR = _ASSETS_DIR / "star.svg"
_STARRED = _ASSETS_DIR / "starred.svg"
_UNSTARRED = _ASSETS_DIR / "unstarred.svg"
_BOOKMARK = _ASSETS_DIR / "bookmark.svg"
_DROPDOWN = _ASSETS_DIR / "dropdown.svg"

novaplay_logo = QIcon(str(_NOVAPLAY_LOGO))
novaplay_icon = QIcon(str(_NOVAPLAY_ICON))
play_icon = QIcon(str(_PLAY))
pause_icon = QIcon(str(_PAUSE))
stop_icon = QIcon(str(_STOP))
mute_icon = QIcon(str(_MUTE))
volume_icon = QIcon(str(_VOLUME))
audio_icon = QIcon(str(_AUDIO))
subtitle_icon = QIcon(str(_SUBTITLE))
plus_icon = QIcon(str(_PLUS))
big_plus_icon = QIcon(str(_BIG_PLUS))
minus_icon = QIcon(str(_MINUS))
fullscreen_icon = QIcon(str(_FULL_SCR))
restore_screen_icon = QIcon(str(_RESTORE_SCR))
new_folder_icon = QIcon(str(_NEW_FOLDER))
folder_icon = QIcon(str(_FOLDER))
menu_icon = QIcon(str(_MENU))
refresh_icon = QIcon(str(_REFRESH))
settings_icon = QIcon(str(_SETTINGS))
trash_icon    = QIcon(str(_TRASH))
download_icon = QIcon(str(_DOWNLOAD))
pin_icon = QIcon(str(_PIN))
pinned_icon = QIcon(str(_PINNED))
left_arrow_icon = QIcon(str(_LEFT_ARROW))
right_arrow_icon = QIcon(str(_RIGHT_ARROW))
home_icon = QIcon(str(_HOME))
star_icon = QIcon(str(_STAR))
starred_icon = QIcon(str(_STARRED))
unstarred_icon = QIcon(str(_UNSTARRED))
bookmark_icon = QIcon(str(_BOOKMARK))
dropdown_icon = QIcon(str(_DROPDOWN))
