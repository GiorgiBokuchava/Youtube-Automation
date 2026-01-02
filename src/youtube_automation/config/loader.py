import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path.cwd()


def load_env() -> None:
    load_dotenv()


def load_settings() -> dict:
    settings_path = BASE_DIR / "config" / "settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
