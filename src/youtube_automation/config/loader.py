import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[3]


import os

def load_env(channel: str | None = None) -> None:
    """Load .env and map optional channel-prefixed vars (e.g. ANIMALS_VAR -> VAR)."""
    load_dotenv()
    if not channel:
        return
    prefix = f"{channel.upper()}_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            base_key = key[len(prefix) :]
            os.environ[base_key] = value


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(channel: str, *, shorts: bool = False) -> dict:
    base = _load_yaml(BASE_DIR / "config" / "base.yaml")
    channel_cfg = _load_yaml(BASE_DIR / "config" / "channels" / f"{channel}.yaml")

    merged = _deep_merge(base, channel_cfg)
    if shorts:
        # Load shorts-specific channel config
        shorts_path = BASE_DIR / "config" / "shorts" / f"{channel}.yaml"
        if shorts_path.exists():
            merged = _deep_merge(merged, _load_yaml(shorts_path))
        
        # Load shared shorts publishing/general config
        publish_path = BASE_DIR / "config" / "shorts" / "publish.yaml"
        if publish_path.exists():
            merged = _deep_merge(merged, _load_yaml(publish_path))
            
        merged["content_type"] = "shorts"
    else:
        merged["content_type"] = "long_form"
    return merged
