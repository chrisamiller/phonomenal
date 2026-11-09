import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = Path(os.environ.get("SPELLING_SETTINGS", ROOT / "settings.toml"))
DATA_DIR = Path(os.environ.get("SPELLING_DATA_DIR", ROOT / "data"))


def load_settings() -> dict:
    """Read settings fresh each time so edits apply without a restart."""
    with open(SETTINGS_PATH, "rb") as f:
        return tomllib.load(f)
