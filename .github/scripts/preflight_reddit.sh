#!/usr/bin/env bash
# yt-dlp preflight for Publish workflow. Cookie download probe is best-effort (warnings only).
set -euo pipefail

CHANNEL="${CHANNEL:-animals}"
REDDIT_COOKIES_FILE="${REDDIT_COOKIES_FILE:-reddit_cookies.txt}"
IMAGE="${IMAGE:?IMAGE is required}"
DEFAULT_URL="https://www.reddit.com/r/StartledCats/comments/17cn6g6/"

case "${CHANNEL}" in
  dashcam)
    REDDIT_PREFLIGHT_URL="https://www.reddit.com/r/Roadcam/comments/1tjyih5/"
    ;;
  animals)
    REDDIT_PREFLIGHT_URL="${DEFAULT_URL}"
    ;;
  *)
    REDDIT_PREFLIGHT_URL="${REDDIT_PREFLIGHT_URL_DEFAULT:-${DEFAULT_URL}}"
    ;;
esac

echo "REDDIT_PREFLIGHT_URL=${REDDIT_PREFLIGHT_URL}" >>"${GITHUB_ENV}"
echo "Reddit preflight URL (channel=${CHANNEL}): ${REDDIT_PREFLIGHT_URL}"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "${GITHUB_WORKSPACE}:/app" \
  -w /app \
  --entrypoint yt-dlp \
  "${IMAGE}" \
  --version

if [ -z "${REDDIT_COOKIES:-}" ] || [ ! -s "${REDDIT_COOKIES_FILE}" ]; then
  echo "::warning::REDDIT_COOKIES is not set for environment '${CHANNEL}'. Skipping Reddit download preflight — some posts may require cookies and fail during sourcing. Add REDDIT_COOKIES (base64 Netscape cookie file) to this environment if downloads fail."
  exit 0
fi

echo "Cookie preflight: ${REDDIT_COOKIES_FILE} → ${REDDIT_PREFLIGHT_URL}"
if ! docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "${GITHUB_WORKSPACE}:/app" \
  -w /app \
  --entrypoint yt-dlp \
  "${IMAGE}" \
  --cookies "/app/${REDDIT_COOKIES_FILE}" --skip-download \
  "${REDDIT_PREFLIGHT_URL}"; then
  echo "::warning::Reddit cookie preflight failed for ${REDDIT_PREFLIGHT_URL} (channel=${CHANNEL}). Continuing — yt-dlp may still succeed on other posts. Cookies can work locally but fail on GitHub Actions if Reddit distrusts the runner IP or session; refresh cookies or retry later."
fi
