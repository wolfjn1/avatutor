#!/usr/bin/env bash
set -euo pipefail

# Flush local autonomy/* branches: prefer HTTPS with GH_TOKEN (non-interactive)

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
  https://x-access-token:*) slug="${origin_url#https://x-access-token:*@github.com/}"; slug="${slug%.git}" ;;
esac

if [[ -z "$slug" ]]; then
  echo "Could not parse GitHub slug from origin URL: $origin_url"
  exit 0
fi

# Choose remote URL strategy: prefer HTTPS token only if token validates, else SSH
use_https_token=false
if [[ -n "${GH_TOKEN:-}" ]]; then
  if curl -fsS -H "Authorization: Bearer ${GH_TOKEN}" -H "Accept: application/vnd.github+json" https://api.github.com/user >/dev/null 2>&1; then
    use_https_token=true
  fi
fi
if [[ "$use_https_token" == true ]]; then
  git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${slug}.git" || true
else
  git remote set-url origin "git@github.com:${slug}.git" || true
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
    echo "Push via $(git config --get remote.origin.url) failed for $br."
    if [[ "$use_https_token" == true ]]; then
      echo "Retrying over SSH..."
      git remote set-url origin "git@github.com:${slug}.git" || true
      if ! git push -u origin "$br"; then
        echo "Push failed for $br over HTTPS and SSH. Skipping PR creation."
        # Restore remote based on token validity for subsequent branches
        if [[ "$use_https_token" == true ]]; then
          git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${slug}.git" || true
        fi
        continue
      fi
    else
      echo "Push failed for $br. Skipping PR creation."
      continue
    fi
  fi

  if [[ "$use_https_token" == true ]]; then
    title="$(git log -1 --pretty=%s "$br" | sed 's/"/\\"/g')"
    body_raw="$(git log -1 --pretty=%b "$br")"
    body="$(printf "%s" "$body_raw" | sed 's/"/\\"/g')"
    json_payload="$(printf '{"title":"%s","head":"%s","base":"%s","body":"%s"}' "$title" "$br" "$base" "$body")"
    resp="$(curl -sS -f -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" -X POST "https://api.github.com/repos/$slug/pulls" -d "$json_payload" || true)"
    pr_url="$(printf "%s" "$resp" | sed -n 's/.*"html_url" *: *"\([^"]*\)".*/\1/p' | head -n1)"
    if [[ -n "$pr_url" ]]; then
      echo "Opened PR: $pr_url"
      cto_user="${CTO_GH_USER:-}"
      pr_num="$(printf "%s" "$resp" | sed -n 's/.*"number" *: *\([0-9][0-9]*\).*/\1/p' | head -n1)"
      if [[ -n "$cto_user" && -n "$pr_num" ]]; then
        curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
          -X POST "https://api.github.com/repos/$slug/issues/$pr_num/labels" \
          -d '{"labels":["needs-CTO-review"]}' >/dev/null 2>&1 || true
        curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
          -X POST "https://api.github.com/repos/$slug/pulls/$pr_num/requested_reviewers" \
          -d "{\"reviewers\":[\"$cto_user\"]}" >/dev/null 2>&1 || true
      fi
      api_url="${APP_NOTIFY_URL:-http://localhost:8080/ops/notify_pr}"
      if [[ -n "$api_url" && -n "$pr_num" ]]; then
        curl -sS -X POST -H 'Content-Type: application/json' "$api_url" \
          -d "{\"slug\":\"$slug\",\"branch\":\"$br\",\"pr_number\":$pr_num,\"url\":\"$pr_url\"}" >/dev/null 2>&1 || true
      fi
    else
      echo "PR creation skipped or failed (no valid token)."
    fi
  else
    echo "GH_TOKEN not set or invalid. Skipped PR creation for $br."
  fi

  echo "$br" >> "$STATE_FILE"
done

echo "Done."

