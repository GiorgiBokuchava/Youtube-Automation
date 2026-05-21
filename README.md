# Youtube-Automation

Automated pipeline for YouTube compilations: pull short clips from Reddit (and optionally Instagram), optionally generate AI commentary with TTS, normalize and render each clip, stitch with background music, and upload via the YouTube Data API. A separate **shorts** mode builds vertical uploads from the same stack.

## Requirements

- **Python** 3.10+
- **FFmpeg** and **ffprobe** on `PATH`
- **Reddit**: PRAW credentials; for many subreddits, a Netscape-format cookie file for yt-dlp
- **YouTube**: Google Cloud OAuth client with YouTube Data API enabled, plus a refresh token for uploads
- **AI (optional)** API keys for Gemini, OpenRouter, NVIDIA NIM, or Text Generator, depending on which models you enable

**Runtime split:** develop and run on your machine with a **venv**; **Docker** is the canonical runtime for GitHub Actions (and optional CI parity checks). The same `Dockerfile` defines what runs in CI.

## Local setup (venv)

```bash
python -m venv .venv
```

Activate the venv (`.\.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Unix), then:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Development dependencies (pytest, pytest-mock):

```bash
python -m pip install -e ".[dev]"
```

Optional Instaloader cookie loading (`browser_cookie3`) for Instagram:

```bash
python -m pip install -e ".[instagram]"
```

## Configuration

| Location | Role |
|----------|------|
| `config/base.yaml` | Defaults merged into every channel |
| `config/channels/<name>.yaml` | Per-channel overrides (subreddits, scoring, commentary, publishing) |
| `config/shorts/<name>.yaml` | Shorts-specific overrides when using shorts mode |

Loading logic is in `youtube_automation.config.loader.load_settings`. Used post IDs are tracked in `config/used_<channel>.json` (pruned using `used_horizon_days`). Add a channel by creating `config/channels/<name>.yaml` and passing `--channel <name>`.

## Environment

| Variable | Purpose |
|----------|---------|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | PRAW |
| `REDDIT_COOKIES_FILE` | Optional Netscape cookies path for yt-dlp |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | YouTube OAuth for uploads (values are trimmed) |
| `YT_PRIVACY` | Optional: `public`, `private`, or `unlisted`; overrides YAML `youtube.privacy_status` (e.g. in CI) |
| `GEMINI_API_KEYS`, `OPENROUTER_API_KEYS`, `TEXT_GENERATOR_API_KEY` | Text/TTS providers |

Resolution order: `.env` → channel-prefixed vars (e.g. `ANIMALS_YT_CLIENT_ID`) → `.env.<channel>` → `.env.channels/<channel>.env`.

## CLI

```bash
python -m youtube_automation.app --mode pipeline --channel animals
```

| Mode | Behavior |
|------|-----------|
| `pipeline` | Source → render → optional upload |
| `videos` | Source clips only (Reddit + Instagram per `source_split`; same budgeting/filters as pipeline) |
| `thumbnail` | Generate thumbnail only |
| `shorts` | Shorts pipeline (requires shorts config) |
| `ai-preview` | Call real AI for YouTube title/description/hashtags only; print the full metadata prompt and model output. No downloads, commentary, render, or upload. |

Useful flags: `--dry-run` (no upload), `--cleanup` (remove generated media after a successful run), `--target-duration-minutes`, `--no-commentary`, `--no-music`, `--no-ai-metadata`, `--core-only`, `--debug`.

Tune metadata prompts (API keys required). By default, preview uses channel YAML only (no clip titles). To mirror a real compile, paste sourced post titles into `publishing.ai_preview.sample_clips` (optional; the pipeline never uses this block):

```bash
python -m youtube_automation.app --mode ai-preview --channel animals
```

Output is written to `out/<channel>/ai_preview/latest.txt` (and a timestamped copy). The console only shows model attempts and errors.

**Where prompts and settings live**

| What | Location |
|------|----------|
| System rules, tone tables, output format (`TITLE:` / `DESCRIPTION:` / `HASHTAGS:`) | `src/youtube_automation/publishing/ai_metadata.py` |
| Tone, audience, CTA, max hashtags | `config/channels/<name>.yaml` → `publishing.ai_metadata` |
| Optional real clip titles for preview only | `config/channels/<name>.yaml` → `publishing.ai_preview.sample_clips` |
| Defaults | `config/base.yaml` → `publishing.ai_metadata` |

Edit those YAML fields and re-run; use `--debug` if you need verbose provider logs.

Partial failures (commentary, TTS, per-clip render) are logged and stored on the session under `pipeline_errors`.

## GitHub Actions (Docker)

**Order:** run [`.github/workflows/build-image.yml`](.github/workflows/build-image.yml) first so `ghcr.io/<owner>/<repo>:latest` exists, then [`.github/workflows/publish.yml`](.github/workflows/publish.yml). Publish **pulls** that image (no local build, pip, or ffmpeg install on the runner).

Publish runs preflight steps and the pipeline **inside the container**, with the repo mounted at `/app` so `config/used_*.json` updates land in the workspace for the commit step. Set repository or environment secrets as documented in the workflow file. Optional Actions variable `YT_PRIVACY_STATUS` overrides YAML privacy when set. Jobs can target per-channel GitHub Environments so credentials stay isolated.

### Container image on GHCR

[`.github/workflows/build-image.yml`](.github/workflows/build-image.yml) builds the Dockerfile **`runtime`** stage and pushes to [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry):

- `ghcr.io/<owner>/<repo>:latest`
- `ghcr.io/<owner>/<repo>:<commit-sha>`

It uses Docker Buildx and GitHub Actions layer caching. It runs on pushes to `main` when image-related files change, or via **Actions → Build Docker image → Run workflow**.

Local development does not use GHCR. Build on your machine with `docker compose build` or `docker build` (see below).

If CI shows `invalid_grant` on token refresh, typical causes are OAuth app still in **Testing** (refresh tokens expire ~weekly), mismatched client vs refresh token, or stale secrets. The workflow includes a YouTube OAuth preflight so bad tokens fail early.

## Docker (CI / optional parity)

You do not need Docker for day-to-day development. Use it to reproduce the CI environment or debug container-only issues.

Build the runtime image:

```bash
docker compose build
# or: docker build -t youtube-automation:local .
```

Run the same CLI as locally (entrypoint is `python -m youtube_automation.app`). On Linux/macOS, match the host user when bind-mounting the repo. On Windows, omit `--user` / `-e HOME=/tmp`.

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "${PWD}:/app" \
  -w /app \
  youtube-automation:local \
  --mode pipeline --channel animals --dry-run
```

[`compose.yaml`](compose.yaml) mirrors CI bind mounts (`config/`, `out/`, `downloads/`, `sessions/`, etc.) for optional local parity:

```bash
docker compose run --rm app --mode pipeline --channel animals --dry-run
```

To run pytest the same way CI could:

```bash
docker compose run --rm test
```

## Troubleshooting

**Some clips fail to render but the video completes** — Individual clip failures are skipped if at least one clip renders. Inspect the latest session JSON (`config/used_<channel>.json`) under `pipeline_errors` for `clip_id`, paths, and FFmpeg stderr when present.

**FFmpeg** — Log lines like `render_clip clip=… path_kind=…` show which render path ran. Errors distinguish preflight (bad input), ffmpeg (non-zero exit), and output validation (empty or no video stream after encode).

**Instagram `checkpoint_required` / 400 on GraphQL** — Meta wants a security check before API use. Complete it in the Instagram app or on the web while logged in as the same account, then export a **fresh** Instaloader session from a normal network (not a datacenter), base64 it into `INSTAGRAM_SESSION_B64`, and re-run. For emergencies only, set `INSTAGRAM_SKIP_TEST_LOGIN=1` to skip the session probe (sourcing may still fail). Optional: `INSTAGRAM_PREFER_DISK_SESSION=1` prefers an existing validated `sessions/instagram.session` over rewriting from the secret.

## Repository layout

- `src/youtube_automation/` — application code
- `tests/` — unit, contract, integration, and pipeline tests
- `config/` — YAML defaults and channel definitions

## Tests

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

By default, tests marked `integration` (live APIs, network) are skipped. To run them:

```bash
python -m pytest -m integration
```

Optional CI parity:

```bash
docker compose run --rm test
```
