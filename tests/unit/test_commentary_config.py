from youtube_automation.pipeline import commentary_enabled


def test_commentary_enabled_false_when_disabled_in_yaml():
    assert commentary_enabled({"commentary": {"enabled": False, "every_nth": 3}}) is False


def test_commentary_enabled_true_when_enabled_and_every_nth_positive():
    assert commentary_enabled({"commentary": {"enabled": True, "every_nth": 3}}) is True


def test_commentary_enabled_false_when_every_nth_zero():
    assert commentary_enabled({"commentary": {"every_nth": 0}}) is False


def test_commentary_enabled_defaults_on():
    assert commentary_enabled({}) is True
