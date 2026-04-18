from pathlib import Path

DOWNLOADS = Path("downloads")
THUMBS = Path("thumbnails")

DOWNLOADS.mkdir(exist_ok=True)
THUMBS.mkdir(exist_ok=True)
