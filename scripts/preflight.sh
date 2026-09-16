#!/usr/bin/env bash
# scripts/preflight.sh
#
# Fast local pre-flight so a trivial ImportError/lint break is caught in
# seconds-to-a-minute instead of after a full CI round-trip.
#
# Steps:
#   1. ruff check <RUFF_TARGET>   report-only by default (STRICT_LINT=1 to gate)
#   2. import smoke               FATAL: catches broken src imports
#   3. pytest --collect-only      FATAL: imports every test module -> ImportError
#
# `--collect-only` does NOT execute tests, but it does import conftest.py, so a
# missing local DB may print connection warnings. Collection still succeeds.
#
# Overridable env vars:
#   VENV=<path>            venv dir (default: .venv3.14-ubuntu26.04)
#   IMPORT_MODULE=<module> package to import (repo-specific default below)
#   PYTEST_TARGET=<path>   collection target (default: tests)
#   RUFF_TARGET=<path>     lint target (default: src)
#   STRICT_LINT=1          make ruff failures fatal (default: report-only)
#   SKIP_LINT=1 / SKIP_IMPORT=1 / SKIP_COLLECT=1
set -uo pipefail

cd "$(dirname "$0")/.."

VENV="${VENV:-.venv3.14-ubuntu26.04}"
PY="$VENV/bin/python"
RUFF="$VENV/bin/ruff"
IMPORT_MODULE="${IMPORT_MODULE:-rhosocial.activerecord.backend.impl.bigquery}"
PYTEST_TARGET="${PYTEST_TARGET:-tests}"
RUFF_TARGET="${RUFF_TARGET:-src}"

if [ ! -x "$PY" ]; then
  echo "preflight: venv python not found at $VENV (set VENV=...)" >&2
  exit 2
fi

fail=0

if [ "${SKIP_LINT:-0}" != "1" ]; then
  echo "==> [1/3] ruff check $RUFF_TARGET"
  if [ -x "$RUFF" ]; then lint_cmd=("$RUFF"); else lint_cmd=("$PY" -m ruff); fi
  if ! "${lint_cmd[@]}" check "$RUFF_TARGET"; then
    if [ "${STRICT_LINT:-0}" = "1" ]; then
      echo "preflight: lint failed (STRICT_LINT=1)" >&2
      fail=1
    else
      echo "preflight: lint issues found (non-fatal; set STRICT_LINT=1 to gate)"
    fi
  fi
else
  echo "==> [1/3] ruff check (skipped)"
fi

if [ "${SKIP_IMPORT:-0}" != "1" ]; then
  echo "==> [2/3] import smoke: $IMPORT_MODULE"
  if ! "$PY" -c "import $IMPORT_MODULE"; then
    echo "preflight: import of '$IMPORT_MODULE' failed" >&2
    fail=1
  fi
else
  echo "==> [2/3] import smoke (skipped)"
fi

if [ "${SKIP_COLLECT:-0}" != "1" ]; then
  echo "==> [3/3] pytest --collect-only $PYTEST_TARGET (no tests executed)"
  log="$(mktemp)"
  if ! PYTHONPATH=tests "$PY" -m pytest "$PYTEST_TARGET" \
        --collect-only -q -p no:cacheprovider > "$log" 2>&1; then
    echo "preflight: test collection failed (ImportError?):" >&2
    grep -E "ImportError|ModuleNotFoundError|NameError|ERROR collecting" "$log" | head -30 >&2
    fail=1
  fi
  rm -f "$log"
else
  echo "==> [3/3] pytest --collect-only (skipped)"
fi

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "preflight: FAILED — fix the above before committing/pushing."
  exit 1
fi

echo ""
echo "preflight: OK"
