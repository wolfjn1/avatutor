#!/usr/bin/env bash
set -euo pipefail
# Force mocks so tests never hit external providers
export MODEL_PROVIDER=echo
export STT_PROVIDER=mock
export TTS_PROVIDER=mock
pytest -q


