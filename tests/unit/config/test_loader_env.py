from pathlib import Path

from youtube_automation.config import loader


def _clear(monkeypatch, *keys: str) -> None:
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_load_env_applies_channel_prefixed_variables(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(loader, "BASE_DIR", tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "YT_CLIENT_ID=global-client",
                "ANIMALS_YT_CLIENT_ID=animals-client",
            ]
        ),
        encoding="utf-8",
    )

    _clear(monkeypatch, "YT_CLIENT_ID", "ANIMALS_YT_CLIENT_ID")

    loader.load_env("animals")

    assert loader.os.getenv("YT_CLIENT_ID") == "animals-client"


def test_load_env_channel_file_overrides_prefixed_value(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(loader, "BASE_DIR", tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "ANIMALS_YT_CLIENT_ID=animals-prefix-client",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".env.animals").write_text(
        "YT_CLIENT_ID=animals-file-client",
        encoding="utf-8",
    )

    _clear(monkeypatch, "YT_CLIENT_ID", "ANIMALS_YT_CLIENT_ID")

    loader.load_env("animals")

    assert loader.os.getenv("YT_CLIENT_ID") == "animals-file-client"


def test_load_env_channel_subdir_file_has_highest_priority(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(loader, "BASE_DIR", tmp_path)
    (tmp_path / ".env").write_text("YT_CLIENT_ID=global-client", encoding="utf-8")
    (tmp_path / ".env.animals").write_text(
        "YT_CLIENT_ID=dot-env-channel-client",
        encoding="utf-8",
    )
    env_dir = tmp_path / ".env.channels"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / "animals.env").write_text(
        "YT_CLIENT_ID=channels-dir-client",
        encoding="utf-8",
    )

    _clear(monkeypatch, "YT_CLIENT_ID")

    loader.load_env("animals")

    assert loader.os.getenv("YT_CLIENT_ID") == "channels-dir-client"
