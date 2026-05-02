from youtube_automation.media.shorts_sourcing import _shorts_clip_allocation


def test_allocation_both_sources_guarantees_mix_for_n_ge_2():
    r_n, ig_n = _shorts_clip_allocation(
        6, 0.85, 0.15, reddit_ok=True, instagram_ok=True
    )
    assert r_n + ig_n == 6
    assert ig_n >= 1
    assert r_n >= 1


def test_allocation_instagram_only_when_no_reddit():
    r_n, ig_n = _shorts_clip_allocation(
        4, 0.5, 0.5, reddit_ok=False, instagram_ok=True
    )
    assert (r_n, ig_n) == (0, 4)
