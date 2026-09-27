#!/usr/bin/env bash
# scripts/install-git-hooks.sh
#
# Installs an optional pre-commit hook that runs scripts/preflight.sh so a
# broken import/lint is caught before the commit (and before a CI round-trip).
# Bypass a single commit with: git commit --no-verify
#
# Re-run this after pulling, and re-run it from the repository root. To remove
# the hook, delete .git/hooks/pre-commit (or the core.hooksPath directory).
set -euo pipefail

cd "$(dirname "$0")/.."

# git ignores .git/hooks entirely once core.hooksPath is set, so a hook written
# there would never run while this script still reported success.
HOOKS_PATH="$(git config core.hooksPath || true)"
if [ -n "$HOOKS_PATH" ]; then
  echo "install-git-hooks: core.hooksPath is set to '$HOOKS_PATH'." >&2
  echo "install-git-hooks: .git/hooks is ignored by git; writing the hook to" >&2
  echo "                 '$HOOKS_PATH/pre-commit' instead." >&2
  HOOK="$HOOKS_PATH/pre-commit"
  mkdir -p "$HOOKS_PATH"
else
  HOOK=".git/hooks/pre-commit"
  if [ ! -d .git/hooks ]; then
    echo "install-git-hooks: .git/hooks not found (not a git repo?)" >&2
    exit 2
  fi
fi

cat > "$HOOK" <<'HOOK_BODY'
#!/usr/bin/env bash
# Installed by scripts/install-git-hooks.sh — runs the local pre-flight.
# Skip with: git commit --no-verify
#
# The guard below matters on older revisions: this hook is a local, untracked
# artifact, so it survives a checkout of a commit that predates
# scripts/preflight.sh. Without the guard, exec fails with a bare
# "No such file or directory" and blocks the commit with nothing to act on.
PREFLIGHT="$(git rev-parse --show-toplevel)/scripts/preflight.sh"
[ -x "$PREFLIGHT" ] || exit 0
exec "$PREFLIGHT"
HOOK_BODY
chmod +x "$HOOK"

echo "install-git-hooks: installed $HOOK -> scripts/preflight.sh"
