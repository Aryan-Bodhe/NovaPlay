from pathlib import Path
from typing import Literal

from exceptions.themes import ThemeException

_THEME = {
    'novaplay': Path('themes/novaplay.qss'),
    'dark': Path('themes/dark.qss'),
    'light': Path('themes/light.qss')
}

_ROOT = Path(__file__).resolve().parent.parent

def load_theme(
    theme: Literal['novaplay', 'dark', 'light']
):
    _path = _THEME.get(theme)
    if _path is None:
        raise ThemeException(f"Unknown theme: {theme}")
    full_path = (_ROOT / _path).resolve()
    try:
        with open(full_path, encoding="utf-8") as f:
            theme_qss = f.read()
        return theme_qss
    except Exception as e:
        raise ThemeException(e) from e
