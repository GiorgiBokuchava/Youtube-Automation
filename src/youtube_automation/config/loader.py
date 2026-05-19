import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[3]


def load_env(channel: str | None = None) -> None:
    """Load env files under BASE_DIR and map channel-prefixed vars (e.g. ANIMALS_VAR -> VAR)."""
    env_path = BASE_DIR / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)

    if not channel:
        return

    prefix = f"{channel.upper()}_"
    for key, value in list(os.environ.items()):
        if key.startswith(prefix):
            base_key = key[len(prefix) :]
            os.environ[base_key] = value

    ch_file = BASE_DIR / f".env.{channel}"
    if ch_file.is_file():
        load_dotenv(ch_file, override=True)

    ch_nested = BASE_DIR / ".env.channels" / f"{channel}.env"
    if ch_nested.is_file():
        load_dotenv(ch_nested, override=True)


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
        shorts_path = BASE_DIR / "config" / "shorts" / f"{channel}.yaml"
        if shorts_path.exists():
            merged = _deep_merge(merged, _load_yaml(shorts_path))
        publish_path = BASE_DIR / "config" / "shorts" / "publish.yaml"
        if publish_path.exists():
            merged = _deep_merge(merged, _load_yaml(publish_path))
        merged["content_type"] = "shorts"
    else:
        merged["content_type"] = "long_form"
    return merged
