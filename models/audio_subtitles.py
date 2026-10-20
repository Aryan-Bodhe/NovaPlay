from pydantic import BaseModel

class Subtitle(BaseModel):
    id: int
    name: str

class AudioTrack(BaseModel):
    id: int
    name: str
