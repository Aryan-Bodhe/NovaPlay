from pathlib import Path

from pydantic import BaseModel


class Bookmark(BaseModel):
    title: str
    url: str


class AppSettings(BaseModel):
    watch_dirs:    list[str]      = []
    pinned_dirs:   list[str]      = []
    bookmarks:     list[Bookmark] = []
    last_volume:   int            = 80
    sidebar_width: int            = 300
    theme:            str  = "purple"   # "vscode" | "purple"
    download_dir:     str  = str(Path.home() / "Downloads" / "NovaPlay")
    adblocker_enabled: bool = True
