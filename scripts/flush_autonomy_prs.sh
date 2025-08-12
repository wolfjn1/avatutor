#!/usr/bin/env bash
set -euo pipefail

# Flush local autonomy/* branches: push via SSH and open PRs (if GH_TOKEN is available)

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Load GH_TOKEN from file if not provided in environment
if [[ -z "${GH_TOKEN:-}" ]]; then
  TOKEN_FILE="$HOME/.config/avatutor/gh_token"
  if [[ -f "$TOKEN_FILE" ]]; then
    GH_TOKEN="$(cat "$TOKEN_FILE" | tr -d '\n')"
  fi
fi

origin_url="$(git config --get remote.origin.url || true)"
if [[ -z "$origin_url" ]]; then
  echo "No origin remote configured; nothing to do."
  exit 0
fi

slug=""
case "$origin_url" in
  git@github.com:*) slug="${origin_url#git@github.com:}"; slug="${slug%.git}" ;;
  https://github.com/*) slug="${origin_url#https://github.com/}"; slug="${slug%.git}" ;;
esac

if [[ -z "$slug" ]]; then
  echo "Could not parse GitHub slug from origin URL: $origin_url"
  exit 0
fi

ssh_url="git@github.com:$slug.git"
if [[ "$origin_url" != "$ssh_url" ]]; then
  echo "Setting origin to SSH: $ssh_url"
  git remote set-url origin "$ssh_url" || true
fi

# Determine default base branch
base="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || true)"
if [[ -z "$base" ]]; then
  if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then base="main";
  elif git ls-remote --exit-code --heads origin master >/dev/null 2>&1; then base="master";
  else base="main"; fi
fi

STATE_FILE=".git/autonomy_flushed"
touch "$STATE_FILE"

branches="$(git for-each-ref --format='%(refname:short)' refs/heads/autonomy/* 2>/dev/null || true)"
if [[ -z "$branches" ]]; then
  echo "No local autonomy/* branches to flush."
  exit 0
fi

for br in $branches; do
  if grep -Fxq "$br" "$STATE_FILE"; then
    echo "Already flushed $br"
    continue
  fi

  echo "Pushing $br ..."
  if ! git push -u origin "$br"; then
    echo "Push failed for $br. Skipping PR creation."
    continue
  fi

  if [[ -n "${GH_TOKEN:-}" ]]; then
    title="$(git log -1 --pretty=%s "$br" | sed 's/"/\\"/g')"
    body_raw="$(git log -1 --pretty=%b "$br")"
    body="$(printf "%s" "$body_raw" | sed 's/"/\\"/g')"
    json_payload="$(printf '{"title":"%s","head":"%s","base":"%s","body":"%s"}' "$title" "$br" "$base" "$body")"
    resp="$(curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" -X POST "https://api.github.com/repos/$slug/pulls" -d "$json_payload" || true)"
    pr_url="$(printf "%s" "$resp" | sed -n 's/.*"html_url" *: *"\([^"]*\)".*/\1/p' | head -n1)"
    if [[ -n "$pr_url" ]]; then
      echo "Opened PR: $pr_url"
    else
      echo "PR creation response (truncated): $(printf "%s" "$resp" | head -c 200)"
    fi
  else
    echo "GH_TOKEN not set. Skipped PR creation for $br."
  fi

  echo "$br" >> "$STATE_FILE"
done

echo "Done."

