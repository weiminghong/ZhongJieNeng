#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT_ROOT"
mkdir -p runtime/tmp runtime/cache
export TMPDIR="$PROJECT_ROOT/runtime/tmp"
export XDG_CACHE_HOME="$PROJECT_ROOT/runtime/cache"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PROJECT_ROOT/.venv/bin/python" -m cecep_console.server --host 0.0.0.0 --port "${CECEP_PORT:-8501}"

