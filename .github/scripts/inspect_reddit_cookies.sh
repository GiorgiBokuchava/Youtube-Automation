#!/usr/bin/env bash
# Print safe Reddit cookie file metadata only (no values or secret material).
set -euo pipefail

file="${1:?cookie file path required}"

if [ ! -f "$file" ]; then
  echo "cookie file exists: false"
  exit 0
fi

size="$(wc -c <"$file" | tr -d ' ')"
lines="$(wc -l <"$file" | tr -d ' ')"

if grep -q '^# Netscape HTTP Cookie File' "$file"; then
  netscape="true"
else
  netscape="false"
fi

if grep -qi 'reddit\.com' "$file"; then
  reddit="true"
else
  reddit="false"
fi

echo "cookie file exists: true"
echo "byte size: ${size}"
echo "line count: ${lines}"
echo "netscape header: ${netscape}"
echo "reddit.com present: ${reddit}"
echo "cookie names:"
awk -F '\t' 'NF >= 7 && $1 !~ /^#/ { print $6 }' "$file" | sort -u
