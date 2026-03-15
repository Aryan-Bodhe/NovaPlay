from pathlib import Path
from guessit import guessit

from config.config import VIDEO_EXT
from models.series_data import Episode, Season, Series


def scan_series(series_path: Path) -> Series:

    seasons: list[Season] = []

    for season_dir in sorted(series_path.iterdir()):

        if not season_dir.is_dir():
            continue

        episodes: list[Episode] = []

        for file in sorted(season_dir.iterdir()):

            if file.suffix.lower() not in VIDEO_EXT:
                continue

            info = guessit(file.name)

            season_no = info.get("season")
            episode_no = info.get("episode")

            if episode_no is None:
                continue

            episodes.append(
                Episode(
                    path=file,
                    season=season_no or 0,
                    episode_no=episode_no,
                )
            )

        if episodes:
            seasons.append(
                Season(
                    path=season_dir,
                    season_no=episodes[0].season,
                    episodes=sorted(
                        episodes,
                        key=lambda e: e.episode_no
                    ),
                )
            )

    return Series(
        name=series_path.name,
        path=series_path,
        seasons=sorted(seasons, key=lambda s: s.season_no),
    )