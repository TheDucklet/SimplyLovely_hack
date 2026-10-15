import os
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TRUE_VALUES = {"1", "true", "yes", "on"}
STORAGE_MODES = {"files", "postgres"}


def config_dir() -> Path:
    return Path(os.environ.get("GEOSTART_CONFIG_DIR") or REPOSITORY_ROOT / "config")


def data_dir() -> Path:
    return Path(os.environ.get("GEOSTART_DATA_DIR") or REPOSITORY_ROOT / "data")


def research_dir() -> Path:
    return REPOSITORY_ROOT / "research"


def processed_dir(city_code: str) -> Path:
    return data_dir() / "processed" / city_code


def use_mocks() -> bool:
    return os.environ.get("GEOSTART_USE_MOCKS", "false").strip().lower() in TRUE_VALUES


def cors_origins() -> list[str]:
    raw_origins = os.environ.get("GEOSTART_CORS_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def storage_mode() -> str:
    mode = os.environ.get("GEOSTART_STORAGE", "files").strip().lower()
    if mode not in STORAGE_MODES:
        raise ValueError(
            f"GEOSTART_STORAGE должен быть одним из {', '.join(sorted(STORAGE_MODES))}, получено {mode}"
        )
    return mode
