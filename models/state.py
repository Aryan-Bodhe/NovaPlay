from pydantic import BaseModel

class PlayerState(BaseModel):
    series: str
    season: int | None
    episode: int
    pos: int = 0