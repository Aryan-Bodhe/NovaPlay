from pydantic import BaseModel
from pathlib import Path

class Episode(BaseModel):
    path: Path
    season: int
    episode_no: int
    

class Season(BaseModel):
    path: Path
    episodes: list[Episode]
    season_no: int


class Series(BaseModel):
    name: str
    seasons: list[Season]
    path: Path
