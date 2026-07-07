# Youtube-Automation

Builds YouTube compilation videos from Reddit and Instagram clips: download, normalize, optional commentary, background music, stitch, upload.

## Setup

**Requires:** Python 3.10+, FFmpeg/ffprobe, credentials in `.env` (see below).

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pip install -e ".[dev]"
pip install -e ".[music-detection]"                # optional; config/base.yaml
```

## Usage

```bash
python -m youtube_automation.app --mode pipeline --channel animals
python -m youtube_automation.app --mode pipeline --channel animals --dry-run --debug
```

| Mode | Description |
|------|-------------|
| `pipeline` | Full run (`--dry-run` skips upload) |
| `videos` | Download clips only |
| `shorts` | Vertical shorts |
| `thumbnail` / `ai-preview` | Thumbnail or metadata only |

Flags: `--cleanup`, `--no-music`, `--no-commentary`, `--target-duration-minutes`, `--debug`.

Config: `config/base.yaml` + `config/channels/<name>.yaml`. Run with `--channel <name>`.

## Credentials (`.env`)

Load order: `.env` → channel prefix mapping → `.env.<channel>`.

**Channel prefixes:** vars like `ANIMALS_REDDIT_CLIENT_ID` become `REDDIT_CLIENT_ID` when you run `--channel animals`. Same pattern for `DASHCAM_*`. Shared vars (`REDDIT_COOKIES`, `INSTAGRAM_SESSION_B64`) stay unprefixed.

### Reddit API (listing posts — PRAW)

Used to browse subreddits and read metadata. **Not** enough to download videos.

1. [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → **create app** → type **script**
2. Set in `.env` (per channel or global):

```env
ANIMALS_REDDIT_CLIENT_ID=...
ANIMALS_REDDIT_CLIENT_SECRET=...
ANIMALS_REDDIT_USER_AGENT=mybot/1.0 by u/yourusername
```

### Reddit cookies (downloading videos — yt-dlp)

Required for many video posts (`Account authentication is required` without them). **Separate from PRAW.** Export a Netscape cookie file while logged into [reddit.com](https://www.reddit.com), then base64-encode it for `.env`:

```bash
python scripts/encode_reddit_cookies_b64.py --cookies path/to/cookies.txt --env --copy
```

```env
REDDIT_COOKIES=...   # one line; trailing = is normal, no quotes needed
```

Refresh when downloads start failing auth again.

### YouTube upload

1. [Google Cloud Console](https://console.cloud.google.com/) → project → enable **YouTube Data API v3**
2. **APIs & Services → Credentials** → **OAuth 2.0 Client** (Desktop app) → copy client id + secret
3. Generate a **refresh token** with scope `https://www.googleapis.com/auth/youtube.upload` ([OAuth 2.0 Playground](https://developers.google.com/oauthplayground/) with your client, or a one-off local OAuth script)
4. Put all three in `.env` (per channel):

```env
ANIMALS_YT_CLIENT_ID=...
ANIMALS_YT_CLIENT_SECRET=...
ANIMALS_YT_REFRESH_TOKEN=...
```

If upload fails with `invalid_grant`, the OAuth app may still be in **Testing** (tokens expire ~weekly) — publish the consent screen or regenerate the refresh token.

### AI (metadata / commentary)

Only needed if those features are enabled in YAML. Comma-separate multiple keys for rotation.

| Variable | Where to get it |
|----------|-----------------|
| `GEMINI_API_KEYS` | [Google AI Studio](https://aistudio.google.com/apikey) |
| `OPENROUTER_API_KEYS` | [openrouter.ai](https://openrouter.ai/) |
| `NVIDIA_API_KEYS` | [NVIDIA NIM / build](https://build.nvidia.com/) |
| `TEXT_GENERATOR_API_KEY` | Your Text Generator.io account |

Example: `ANIMALS_OPENROUTER_API_KEYS=sk-or-...,sk-or-...`

### Instagram

Enable in channel YAML (`source_split.instagram`, `instagram.hashtags` / `accounts`, `instagram.session_username`).

Instaloader uses a **session pickle** built from browser cookies. Base64-encode it for one shared secret (nothing is written under `sessions/`):

```bash
python scripts/encode_instagram_session_b64.py --cookies path/to/cookies.txt --env --copy
```

```env
INSTAGRAM_SESSION_B64=...   # one line; trailing = is normal, no quotes needed
```

Re-run the encode script after `login_required` or a security checkpoint.

## CI

1. **Build Docker image** → `ghcr.io/<owner>/<repo>:latest`
2. **Publish video** — upload your entire local `.env` as one repository secret:

```bash
gh secret set DOTENV < .env
```

The workflow writes that file on the runner and uses the same channel-prefix rules as local (`ANIMALS_*`, `DASHCAM_*`, shared `REDDIT_COOKIES`, `INSTAGRAM_SESSION_B64`). No per-channel GitHub Environments or duplicate secrets.

Optional repo **variables** (not in `.env`): `YT_PRIVACY_STATUS`, `REDDIT_PREFLIGHT_URL`.

`docker compose build` && `docker compose run --rm app --mode pipeline --channel animals --dry-run`

## Tests

```bash
pip install -e ".[dev]"
pytest
```
