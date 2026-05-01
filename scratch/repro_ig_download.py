import sys
from pathlib import Path
import logging

# Add src to sys.path
sys.path.append(str(Path("src").resolve()))

from youtube_automation.instagram.client import (
    build_loader,
    resolve_instagram_session_path,
)
from youtube_automation.instagram.scraper import _download_instagram_video
from youtube_automation.utils.paths import DOWNLOADS
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)


def test_download():
    load_dotenv()

    L = build_loader(
        resolve_instagram_session_path(),
        download_dir=DOWNLOADS,
        session_username="instagram",
    )

    # Try a known shortcode or use one from the previous logs
    shortcode = "DW3jNNhDsIj"

    # We need a media dict. instaloader can fetch it.
    import instaloader

    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        media = post._node  # This is the internal dict structure
        print(f"Media keys: {list(media.keys())}")
        print(f"Shortcode in media: {media.get('code')}")
        print(f"Shortcode in post: {post.shortcode}")

        path = _download_instagram_video(L, shortcode, 1.0, media=media)

        if path:
            print(f"Success! Downloaded to {path}")
        else:
            print("Download failed (returned None)")
    except Exception as e:
        print(f"Exception during test: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_download()
