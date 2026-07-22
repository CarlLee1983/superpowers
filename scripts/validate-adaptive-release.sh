#!/usr/bin/env bash
set -euo pipefail

ROOT="${ADAPTIVE_TEST_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
release_args=()

case "$#" in
  0)
    ;;
  2)
    if [[ "$1" != "--release-tag" || -z "$2" ]]; then
      printf 'usage: validate-adaptive-release.sh [--release-tag TAG]\n' >&2
      exit 2
    fi
    release_args=("--release-tag" "$2")
    ;;
  *)
    printf 'usage: validate-adaptive-release.sh [--release-tag TAG]\n' >&2
    exit 2
    ;;
esac

if [[ "${#release_args[@]}" -eq 0 ]]; then
  "$ROOT/scripts/validate-adaptive-base.py"
else
  "$ROOT/scripts/validate-adaptive-base.py" "${release_args[@]}"
fi
"$ROOT/tests/adaptive-maintenance/run-tests.sh"
"$ROOT/tests/workflow-modes/run-static-tests.sh"
"$ROOT/tests/codex/test-marketplace-manifest.sh"
"$ROOT/tests/codex/test-package-codex-plugin.sh"
"$ROOT/scripts/smoke-codex-install.sh"
"$ROOT/tests/hooks/test-session-start.sh"
