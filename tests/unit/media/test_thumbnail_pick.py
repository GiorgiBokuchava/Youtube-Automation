from types import SimpleNamespace

from youtube_automation.media.thumbnail import _pick_image_url


def test_pick_image_i_redd_it_without_extension():
    s = SimpleNamespace(url="https://i.redd.it/abc123", preview=None)
    assert _pick_image_url(s) == "https://i.redd.it/abc123"


def test_pick_image_from_preview_decodes_html_entities():
    s = SimpleNamespace(
        url="https://www.reddit.com/r/foo/comments/bar/title/",
        preview={
            "images": [
                {
                    "source": {
                        "url": "https://preview.redd.it/foo.jpg?width=640&amp;format=pjpg"
                    }
                }
            ]
        },
    )
    u = _pick_image_url(s)
    assert u and "preview.redd.it" in u
    assert "&amp;" not in u
