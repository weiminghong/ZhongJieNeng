#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export CECEP_DB_PATH="${CECEP_DB_PATH:-$ROOT/runtime/data/cecep.sqlite3}"
export TMPDIR="$ROOT/runtime/tmp"
export XDG_CACHE_HOME="$ROOT/runtime/cache"
export PIP_CACHE_DIR="$ROOT/runtime/cache/pip"
export CECEP_ML_WORKER=1
export CECEP_ML_ROOT="$ROOT/runtime/ml"
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$(dirname "$CECEP_DB_PATH")"
exec 9>"$ROOT/runtime/storage-api.lock"
flock --nonblock 9 || { echo 'storage API already running' >&2; exit 1; }
"$ROOT/.venv/bin/python" -m cecep_console.storage init
exec "$ROOT/.venv/bin/python" -m cecep_console.server --host "${CECEP_API_HOST:-0.0.0.0}" --port "${CECEP_API_PORT:-8503}"
