from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from geostart import settings

DATA_FILES = (
    "hex_features.parquet",
    "competitors.parquet",
    "wages.parquet",
    "addresses.parquet",
    "boundary.geojson",
)


def configure_environment() -> None:
    load_dotenv(settings.REPOSITORY_ROOT / ".env", override=False)


def city_directory(city: str, data_override: Path | None = None) -> Path:
    configure_environment()
    directory = (
        data_override / "processed" / city if data_override is not None else settings.processed_dir(city)
    )
    for name in DATA_FILES:
        if not (directory / name).is_file():
            raise FileNotFoundError(f"Нет файла {directory / name}, распакуйте архив данных")
    return directory


def load_demand_inputs(city: str, data_override: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    directory = city_directory(city, data_override)
    return pd.read_parquet(directory / "hex_features.parquet"), pd.read_parquet(
        directory / "competitors.parquet"
    )


def scores_directory(data_override: Path | None = None) -> Path:
    configure_environment()
    return (data_override if data_override is not None else settings.data_dir()) / "scores"
