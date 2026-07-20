#!/usr/bin/env bash
set -euo pipefail

FAILURES=0

pass() { printf '  [PASS] %s\n' "$1"; }
fail() { printf '  [FAIL] %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

assert_file() {
  local path="$1" label="$2"
  [[ -f "$path" ]] && pass "$label" || fail "$label"
}

assert_contains() {
  local path="$1" text="$2" label="$3"
  rg -Fq -- "$text" "$path" && pass "$label" || fail "$label"
}

assert_not_matches() {
  local path="$1" pattern="$2" label="$3"
  if rg -iq -- "$pattern" "$path"; then fail "$label"; else pass "$label"; fi
}

finish() {
  if [[ "$FAILURES" -ne 0 ]]; then
    printf '\n%d assertion(s) failed\n' "$FAILURES"
    exit 1
  fi
  printf '\nAll assertions passed\n'
}
