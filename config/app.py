from pathlib import Path

# Runtime data directory (settings, state)
APP_DATA_DIR = Path.home() / ".novaplay"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = APP_DATA_DIR / "settings.json"
STATE_FILE = APP_DATA_DIR / "state.json"

# Project-level config files (shipped with the repo, user-editable)
TORRENTS_CONFIG = Path(__file__).parent / "torrents.json"

# Video file extensions recognized by the player
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v")

# Logging
LOGGING_DIR = "logs/"
LOGGING_LIMIT_DAYS = 5
