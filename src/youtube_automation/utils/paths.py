from pathlib import Path

DOWNLOADS = Path("downloads")
THUMBS = Path("thumbnails")


def ensure_workspace_dirs() -> None:
    """Create download/thumbnail dirs on demand (avoid mkdir at import — breaks CI as root)."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
