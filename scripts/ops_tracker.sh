#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Avatutor Ops Tracker ==="
echo "Time: $(date)"
echo "Showing live logs from api/worker/beat and flusher. Press Ctrl-C to stop."

REGEX='cos.update|cto.review|autonomy.proposal|Opened PR|needs-CTO-review|cto-tests-(pass|failed)|design-reviewed|product-reviewed|engineering-reviewed|merged|/ops/notify_pr|PR #|Received task|succeeded in|ERROR|WARNING'

# Tail host flusher logs (if present)
if [[ -f "$HOME/Library/Logs/avatutor_flushprs.out.log" ]] || [[ -f "$HOME/Library/Logs/avatutor_flushprs.err.log" ]]; then
  ( tail -F "$HOME/Library/Logs/avatutor_flushprs.out.log" "$HOME/Library/Logs/avatutor_flushprs.err.log" 2>/dev/null | sed -E 's/^/[flusher] /' ) &
fi

# Stream compose logs; if NO_FILTER=1, show everything; otherwise highlight interesting lines
if [[ "${NO_FILTER:-0}" == "1" ]]; then
  exec docker compose -f infrastructure/docker-compose.yml logs -f -t api worker beat | sed -E 's/^/[compose] /'
else
  exec docker compose -f infrastructure/docker-compose.yml logs -f -t api worker beat | egrep -i "$REGEX" | sed -E 's/^/[compose] /'
fi


