import subprocess
import time
import requests
from pathlib import Path


class VLCPlayer:

    def __init__(
        self,
        password: str = "vlc",
        host: str = "localhost",
        port: int = 8080
    ):
        self.password = password
        self.url = f"http://{host}:{port}/requests/status.json"
        self.proc: subprocess.Popen | None = None

    def get_status(self) -> dict | None:
        try:
            r = requests.get(
                self.url,
                auth=("", self.password),
                timeout=1
            )
            r.raise_for_status()
            return r.json()

        except requests.RequestException:
            return None

    def play_video(self, file: Path | str, start: int = 0) -> int:

        cmd = [
            "vlc",
            "--extraintf=http",
            f"--http-password={self.password}",
            "--start-time",
            str(start),
            "--play-and-exit",
            str(file)
        ]

        self.proc = subprocess.Popen(cmd)

        last_time = start

        while self.proc.poll() is None:

            status = self.get_status()

            if status:
                last_time = status.get("time", last_time)

            time.sleep(1)

        return last_time

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()