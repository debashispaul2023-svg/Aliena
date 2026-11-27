import os
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.toml"


def load_config(path=None) -> dict:
    """Load TOML config; env LOG_SCANNER_CONFIG overrides the default path."""
    target = Path(path or os.environ.get("LOG_SCANNER_CONFIG", DEFAULT_PATH))
    if not target.is_file():
        return {}
    with target.open("rb") as fh:
        return tomllib.load(fh)
