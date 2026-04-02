# YouTube Automation

Python toolchain that sources short videos from Reddit, optionally adds AI commentary and TTS, stitches a compilation with background music, and uploads to YouTube via the Data API.

## Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) and ffprobe on your `PATH` (the app also supports an embedded binary path via `youtube_automation.media.ffmpeg` if configured)
- Reddit API credentials (PRAW) and, for many subreddits, a Reddit cookie file for yt-dlp
- Google Cloud OAuth client (desktop or web) with YouTube Data API enabled, used with a refresh token

## Install

```bash
pip install -r requirements.txt
pip install -e .
```

For development tests:

```bash
pip install -e ".[dev]"
```

Runtime dependencies are also declared in `pyproject.toml`; `requirements.txt` remains a fully pinned lockfile for reproducible installs (for example in CI).

## Configuration

- `config/base.yaml` — defaults merged into every channel.
- `config/channels/<name>.yaml` — per-channel overrides (subreddits, scoring, commentary, YouTube copy templates).

Load order is implemented in `youtube_automation.config.loader.load_settings`.

Session history (used post IDs) is stored in `config/used_<channel>.json` and pruned using `used_horizon_days`.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | PRAW |
| `REDDIT_COOKIES_FILE` | Optional path to Netscape cookie file for yt-dlp |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | YouTube upload OAuth (values are trimmed; use non-breaking secrets with no stray newlines) |
| `YT_PRIVACY` | Optional. When set to `public`, `private`, or `unlisted`, overrides `youtube.privacy_status` from YAML (useful in CI). |
| `GEMINI_API_KEYS`, `OPENROUTER_API_KEYS`, `TEXT_GENERATOR_API_KEY` | AI providers (see code for exact usage) |

Use a local `.env` file if you rely on `python-dotenv` via `load_env()` in the CLI.

## CLI

```bash
python -m youtube_automation.app --mode pipeline --channel animals
```

Modes:

- `pipeline` — full run (source → render → optional upload)
- `videos` — download and list clips only
- `thumbnail` — pick thumbnail only

Useful flags:

- `--dry-run` — build everything but skip YouTube upload
- `--cleanup` — when the run completes successfully, delete generated media under `out/<channel>/`, `thumbnails/`, and `downloads/` (session JSON is kept). If the pipeline aborts, cleanup is skipped so intermediates remain for debugging.
- `--debug` — verbose logging

Partial failures (commentary, TTS, per-clip render, etc.) are logged and recorded under `pipeline_errors` on the saved session.

## GitHub Actions

`.github/workflows/publish.yml` runs the pipeline on a schedule or manually.

1. Set the **Actions variable** `YT_PRIVACY_STATUS` to `public` or `unlisted` when you are ready for uploads to match that visibility (defaults to `private` if the variable is unset).
2. Provide secrets as referenced in the workflow file (Reddit, YouTube OAuth, AI keys, base64-encoded Reddit cookies).

Jobs target a GitHub **Environment** named after the channel (`animals`, `dashcam`). If you define secrets on those environments, they override repository secrets—keep `YT_*` values identical across environments unless you intend different channels per environment.

### YouTube `invalid_grant` / weekly failures

If CI logs show `invalid_grant` or `RefreshError` when refreshing the token:

- **Testing mode:** In [Google Cloud Console](https://console.cloud.google.com/) → *APIs & Services* → *OAuth consent screen*, apps in **Testing** often get refresh tokens that stop working after about **seven days**. **Publish** the app to **Production** (complete verification if Google requires it for the `youtube.upload` scope) so refresh tokens last until revoked.
- **Mismatched client:** `YT_REFRESH_TOKEN` must be issued for the **same** OAuth client as `YT_CLIENT_ID` / `YT_CLIENT_SECRET`.
- **Stale environment secret:** Re-copy the three values from Cloud Console into the Environment secrets GitHub actually uses for that job.

The workflow runs a **YouTube OAuth preflight** (and the pipeline does the same before any Reddit download when not in `--dry-run`) so a bad token fails in seconds instead of after a long render.

The workflow does not print cookie file contents; the Reddit preflight only checks that yt-dlp can read metadata with the cookie file.

## Project layout

- `src/youtube_automation/` — application code
- `tests/` — unit, contract, integration, and mocked pipeline tests
