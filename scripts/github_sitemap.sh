#!/usr/bin/env bash
set -euo pipefail

OUTPUT="${OUTPUT:-github_sitemap.md}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: must be run inside a git repository." >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
if [[ -z "$REMOTE_URL" ]]; then
  echo "Error: no origin remote found." >&2
  exit 1
fi

BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"

REPO_PATH="$REMOTE_URL"
REPO_PATH="${REPO_PATH#git@github.com:}"
REPO_PATH="${REPO_PATH#https://github.com/}"
REPO_PATH="${REPO_PATH#http://github.com/}"
REPO_PATH="${REPO_PATH#ssh://git@github.com/}"
REPO_PATH="${REPO_PATH%.git}"

if [[ "$REPO_PATH" != */* ]]; then
  echo "Error: could not parse GitHub owner/repo from origin: $REMOTE_URL" >&2
  exit 1
fi

GITHUB_BASE="https://github.com/${REPO_PATH}"
RAW_BASE="https://raw.githubusercontent.com/${REPO_PATH}/${BRANCH}"

{
  echo "# GitHub Sitemap"
  echo
  echo "- Repository: \`${REPO_PATH}\`"
  echo "- Branch: \`${BRANCH}\`"
  echo "- Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo
  echo "## Repository URLs"
  echo
  echo "- GitHub: ${GITHUB_BASE}"
  echo "- Branch: ${GITHUB_BASE}/tree/${BRANCH}"
  echo "- Raw base: ${RAW_BASE}"
  echo
  echo "## Files"
  echo
  echo "| Path | GitHub URL | Raw URL |"
  echo "|---|---|---|"

  git ls-files | while IFS= read -r file; do
    encoded_file="${file// /%20}"
    blob_url="${GITHUB_BASE}/blob/${BRANCH}/${encoded_file}"
    raw_url="${RAW_BASE}/${encoded_file}"
    echo "| \`${file}\` | [view](${blob_url}) | [raw](${raw_url}) |"
  done
} > "$OUTPUT"

echo "Wrote sitemap to: $OUTPUT"
