import json
from pathlib import Path

from models.app_settings import AppSettings


class SettingsManager:
    def __init__(self, settings_file: Path):
        self.settings_file = settings_file

    def load(self) -> AppSettings:
        if not self.settings_file.exists():
            return AppSettings()
        try:
            with open(self.settings_file) as f:
                data = json.load(f)
            return AppSettings.model_validate(data)
        except (json.JSONDecodeError, ValueError, TypeError):
            return AppSettings()

    def save(self, settings: AppSettings):
        tmp = self.settings_file.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(settings.model_dump(), f, indent=2)
        tmp.replace(self.settings_file)
