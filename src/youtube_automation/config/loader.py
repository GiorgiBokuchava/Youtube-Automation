import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[3]


def _load_env_file(path: Path, *, override: bool) -> None:
    if path.exists():
        load_dotenv(path, override=override)


def _channel_prefix(channel: str) -> str:
    sanitized = "".join(ch if ch.isalnum() else "_" for ch in channel.upper())
    return f"{sanitized}_"


def _apply_channel_prefixed_env(channel: str) -> None:
    """
    Map CHANNEL-prefixed vars to canonical names.

    Example (for channel=animals):
      ANIMALS_YT_CLIENT_ID -> YT_CLIENT_ID
    """
    prefix = _channel_prefix(channel)
    for key, value in list(os.environ.items()):
        if not key.startswith(prefix):
            continue
        target_key = key[len(prefix) :]
        if not target_key:
            continue
        os.environ[target_key] = value


def load_env(channel: str | None = None) -> None:
    # Global defaults for all channels.
    _load_env_file(BASE_DIR / ".env", override=False)

    if not channel:
        return

    # Optional channel-specific aliases inside the shared environment.
    _apply_channel_prefixed_env(channel)

    # Explicit per-channel env files override everything above.
    _load_env_file(BASE_DIR / f".env.{channel}", override=True)
    _load_env_file(BASE_DIR / ".env.channels" / f"{channel}.env", override=True)


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
