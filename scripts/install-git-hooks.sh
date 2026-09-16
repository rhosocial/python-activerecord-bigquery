#!/usr/bin/env bash
# scripts/install-git-hooks.sh
#
# Installs an optional pre-commit hook that runs scripts/preflight.sh so a
# broken import/lint is caught before the commit (and before a CI round-trip).
# Bypass a single commit with: git commit --no-verify
set -euo pipefail

cd "$(dirname "$0")/.."

HOOK=".git/hooks/pre-commit"
if [ ! -d .git/hooks ]; then
  echo "install-git-hooks: .git/hooks not found (not a git repo?)" >&2
  exit 2
fi

cat > "$HOOK" <<'HOOK_BODY'
#!/usr/bin/env bash
# Installed by scripts/install-git-hooks.sh — runs the local pre-flight.
# Skip with: git commit --no-verify
exec "$(git rev-parse --show-toplevel)/scripts/preflight.sh"
HOOK_BODY
chmod +x "$HOOK"

echo "install-git-hooks: installed $HOOK -> scripts/preflight.sh"
