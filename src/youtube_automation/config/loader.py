import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[3]


def load_env(channel: str | None = None) -> None:
    """
    Load `.env` from the project root (or cwd fallback), then merge `.env.<channel>`
    when present so channel-specific secrets override.
    """
    root_env = BASE_DIR / ".env"
    if root_env.is_file():
        load_dotenv(root_env)
    else:
        load_dotenv()
    if channel:
        extra = BASE_DIR / f".env.{channel}"
        if extra.is_file():
            load_dotenv(extra, override=True)


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


def load_settings(channel: str) -> dict:
    base = _load_yaml(BASE_DIR / "config" / "base.yaml")
    channel_cfg = _load_yaml(BASE_DIR / "config" / "channels" / f"{channel}.yaml")

    return _deep_merge(base, channel_cfg)
