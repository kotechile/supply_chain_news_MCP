"""Configuration loader for the Intelligence MCP system."""

import os
from pathlib import Path
from typing import Any, Dict, List
import yaml
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", BASE_DIR / "config.yaml"))


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml, with environment variable overrides."""
    if not CONFIG_PATH.exists():
        return {}

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # Allow environment overrides for sensitive keys
    db_path_env = os.environ.get("DB_PATH")
    if db_path_env:
        config.setdefault("storage", {})["db_path"] = db_path_env

    # Ensure DB directory exists
    db_path = Path(config.get("storage", {}).get("db_path", "data/intelligence.db"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config.setdefault("storage", {})["db_path"] = str(db_path)

    return config


_CONFIG = None


def get_config() -> Dict[str, Any]:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG
