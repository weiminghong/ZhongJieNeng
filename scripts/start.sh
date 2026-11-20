#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT_ROOT"
mkdir -p runtime/tmp runtime/cache
export TMPDIR="$PROJECT_ROOT/runtime/tmp"
export XDG_CACHE_HOME="$PROJECT_ROOT/runtime/cache"
UPSTREAM="$PROJECT_ROOT/vendor/ai-energy-trading-platform"
export PYTHONPATH="$UPSTREAM${PYTHONPATH:+:$PYTHONPATH}"
cd "$UPSTREAM"

# 复用上游现成的 7 页 HTML 驾驶舱和 22 个 Plotly 图表。
"$PROJECT_ROOT/.venv/bin/python" main.py --export > "$PROJECT_ROOT/runtime/upstream-export.log" 2>&1
exec "$PROJECT_ROOT/.venv/bin/python" -m http.server "${CECEP_PORT:-8501}" --bind 0.0.0.0 --directory "$UPSTREAM"
