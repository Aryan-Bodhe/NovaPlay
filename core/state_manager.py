import json
from pathlib import Path

from models.state import PlayerState

class StateManager:
    def __init__(self, state_file: Path, series_name: str):
        self.state_file = state_file
        self.series_name = series_name

    def load(self) -> PlayerState:

        if not self.state_file.exists():
            return PlayerState(
                series=self.series_name,
                season=None,
                episode=0,
                pos=0,
            )

        try:
            with open(self.state_file) as f:
                data = json.load(f)

            return PlayerState(
                series=self.series_name,
                season=data.get("season"),
                episode=data.get("episode", 0),
                pos=data.get("pos", 0),
            )

        except (json.JSONDecodeError, ValueError, TypeError):
            return PlayerState(
                series=self.series_name,
                season=None,
                episode=0,
                pos=0,
            )

    def save(self, state: PlayerState):
        tmp = self.state_file.with_suffix(".tmp")

        with open(tmp, "w") as f:
            json.dump(state.model_dump(), f)

        tmp.replace(self.state_file)

    def reset(self):
        self.save(
            PlayerState(
                series=self.series_name,
                season=None,
                episode=0,
                pos=0
            )
        )