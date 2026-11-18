#!/usr/bin/env bash
# Run the test tree in shards against the BigQuery emulator.
#
# Every test directory owns its own logical dataset (``tests/support/bigquery``
# derives it from the path), so a whole directory is assigned to one shard and
# no two shards ever reset the same dataset.  Inside a shard the emulator is
# restarted for every test *file*: the goccy emulator degrades as jobs and
# tables accumulate within one instance, and a stale instance is what turns a
# long file into a timeout.
#
# ``COVERAGE=1`` runs each file under ``coverage run --parallel-mode`` and
# combines the shard data files at the end.
set -euo pipefail

SHARDS="${SHARDS:-4}"
BASE_PORT="${BASE_PORT:-9050}"
COVERAGE="${COVERAGE:-0}"
FILE_TIMEOUT="${FILE_TIMEOUT:-480}"
TEST_TIMEOUT="${TEST_TIMEOUT:-120}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Every directory under tests/ that owns test files and does not contain a
# deeper directory that owns its own; each such directory derives one dataset.
UNIT_LIST="$(python - <<'PY'
import pathlib

# CI scope: only these roots run; other feature trees are deferred.
scoped_roots = [
    pathlib.Path("tests/rhosocial/activerecord_bigquery_test/feature/backend"),
    pathlib.Path("tests/rhosocial/activerecord_bigquery_test/feature/basic"),
]
units = []
for _root in scoped_roots:
  if not _root.is_dir():
    continue
  for path in sorted(_root.rglob("*")):
    if not any(part.startswith((".", "_")) or part == "__pycache__" for part in path.parts):
      if not any(path.glob("test_*.py")):
        continue
      if not any(child.parent != path for child in path.rglob("test_*.py")):
        units.append(str(path))

print("\n".join(units))
PY
)"

declare -a SHARD_UNITS=()
for i in $(seq 0 $((SHARDS - 1))); do SHARD_UNITS[$i]=""; done
index=0
while IFS= read -r unit; do
  [ -n "$unit" ] || continue
  SHARD_UNITS[$((index % SHARDS))]="${SHARD_UNITS[$((index % SHARDS))]} $unit"
  index=$((index + 1))
done <<< "$UNIT_LIST"

echo "== $index test directories across $SHARDS shards =="

pids=()
for i in $(seq 0 $((SHARDS - 1))); do
  (
    port=$((BASE_PORT + i))
    container="bq-emulator-$i"
    export BIGQUERY_EMULATOR_PORT="$port"

    start_emulator() {
      docker rm -f "$container" >/dev/null 2>&1 || true
      docker run -d --name "$container" \
        -p "$port:9050" -p "$((port + 10)):9060" \
        ghcr.io/goccy/bigquery-emulator:latest \
        --project=test --dataset=test_dataset >/dev/null
      sleep 4
    }

    for unit in ${SHARD_UNITS[$i]}; do
      for file in "$unit"/test_*.py; do
        [ -e "$file" ] || continue
        echo "=== [shard $i] $file (fresh emulator) ==="
        start_emulator
        set +e
        if [ "$COVERAGE" = "1" ]; then
          timeout "$FILE_TIMEOUT" coverage run --parallel-mode --source=src \
            -m pytest "$file" --tb=short -q -o asyncio_mode=auto \
            --timeout="$TEST_TIMEOUT"
        else
          timeout "$FILE_TIMEOUT" pytest "$file" --tb=short -q \
            -o asyncio_mode=auto --timeout="$TEST_TIMEOUT"
        fi
        rc=$?
        set -e
        if [ "$rc" -eq 5 ]; then
          echo "no tests collected in $file"
        elif [ "$rc" -ne 0 ]; then
          echo "FAILED shard $i: $file (rc=$rc)"
          exit "$rc"
        fi
      done
    done
    echo "=== [shard $i] done ==="
  ) > "/tmp/shard_$i.log" 2>&1 &
  pids+=($!)
done

failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=$((failed + 1))
done

if [ "$failed" -gt 0 ]; then
  for i in $(seq 0 $((SHARDS - 1))); do
    echo "----- shard $i failure detail -----"
    awk '/=+ (ERRORS|FAILURES) =+/{found=1} found' "/tmp/shard_$i.log" | head -120
    echo "----- shard $i log tail -----"
    tail -30 "/tmp/shard_$i.log"
  done
  exit 1
fi

if [ "$COVERAGE" = "1" ]; then
  coverage combine
  coverage xml
  coverage report
fi

echo "== all shards passed =="
