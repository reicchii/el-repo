#!/bin/bash
# Prepares a checkout for work. Safe to run again at any time.
#
#   bash scripts/bootstrap.sh
#
# It checks the tools, installs packages from the lockfiles once they exist,
# and creates the git-ignored folder for downloads and logs.
# The cloud environment, the dev container and a local terminal all run this file.

set -u
cd "$(dirname "$0")/.." || exit 1
status=0

have() { command -v "$1" >/dev/null 2>&1; }

echo "Tools"
for tool in git uv node pnpm; do
  if have "$tool"; then
    printf '  %-5s %s\n' "$tool" "$("$tool" --version 2>/dev/null | head -n 1)"
  else
    printf '  %-5s missing. See SETUP.md section 2\n' "$tool"
    status=1
  fi
done

if have uv; then
  if uv python find 3.12 >/dev/null 2>&1 || uv python install 3.12; then
    printf '  %-5s %s\n' "py" "$(uv python find 3.12 2>/dev/null)"
  else
    echo "  Python 3.12 could not be installed"
    status=1
  fi
fi

if [ -f uv.lock ] && have uv; then
  echo "Python packages from uv.lock"
  uv sync --frozen --all-packages --all-extras --all-groups || status=1
else
  echo "Python packages: skipped, uv.lock arrives with task T01-E"
fi

if [ -f web/pnpm-lock.yaml ] && have pnpm; then
  echo "Web packages from web/pnpm-lock.yaml"
  pnpm -C web install --frozen-lockfile || status=1
else
  echo "Web packages: skipped, web/pnpm-lock.yaml arrives with task T01-W"
fi

mkdir -p data/logs

if [ "$status" -eq 0 ]; then
  echo "Ready. Next: bash scripts/check-network.sh"
else
  echo "Not ready. Fix the lines above, then run this again."
fi
exit "$status"
