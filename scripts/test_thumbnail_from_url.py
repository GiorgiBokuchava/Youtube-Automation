#!/usr/bin/env python3
"""
Download a fixed Reddit image and run the full thumbnail pipeline (no feed search).

From the repo root:

    python scripts/test_thumbnail_from_url.py
    python scripts/test_thumbnail_from_url.py --channel animals --debug
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_automation.config.loader import load_env, load_settings
from youtube_automation.media.thumbnail import (
    THUMBS,
    _download_image,
    build_thumbnail_from_image,
)
from PIL import Image

# Hardcoded test asset (kitten playpen — good for animal YOLO / arrow testing)
TEST_IMAGE_URL = "https://i.redd.it/aoyx561pfsqg1.jpeg"
TEST_SUBMISSION_ID = "aoyx561pfsqg1"


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("urllib3", "praw", "prawcore", "requests", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a thumbnail from a fixed URL using channel YAML settings.",
    )
    parser.add_argument(
        "--channel",
        default="animals",
        help="Channel config name (default: animals)",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    setup_logging(args.debug)
    log = logging.getLogger(__name__)

    load_env(args.channel)
    settings = load_settings(args.channel)

    THUMBS.mkdir(exist_ok=True)
    log.info("Downloading %s", TEST_IMAGE_URL)
    downloaded = _download_image(TEST_IMAGE_URL, THUMBS / TEST_SUBMISSION_ID)
    if not downloaded:
        log.error("Download failed: %s", TEST_IMAGE_URL)
        return 1

    try:
        with Image.open(downloaded) as im:
            result = build_thumbnail_from_image(
                im,
                settings,
                submission_id=TEST_SUBMISSION_ID,
                source_url=TEST_IMAGE_URL,
            )
    finally:
        downloaded.unlink(missing_ok=True)

    if not result:
        log.error("Thumbnail pipeline rejected the image (see logs above)")
        return 1

    log.info("Done: %s", result["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
