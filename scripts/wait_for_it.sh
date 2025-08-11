#!/usr/bin/env bash
set -euo pipefail

HOSTPORT="$1"; shift || true

until nc -z ${HOSTPORT/:/ } ; do
  echo "Waiting for $HOSTPORT..."
  sleep 1
done

exec "$@"


