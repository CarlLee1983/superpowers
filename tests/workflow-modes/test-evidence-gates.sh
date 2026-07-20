#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

assert_count() {
  local path="$1" pattern="$2" expected="$3" label="$4" actual
  actual="$(rg -c -- "$pattern" "$path" || true)"
  [[ "$actual" == "$expected" ]] && pass "$label" || fail "$label"
}

DEBUG="$ROOT/skills/systematic-debugging/SKILL.md"
VERIFY="$ROOT/skills/verification-before-completion/SKILL.md"

for skill in "$DEBUG" "$VERIFY"; do
  assert_contains "$skill" "<WORKFLOW-MODE-DEPTH>" "$(basename "$(dirname "$skill")") defines mode depth"
  assert_count "$skill" '^<WORKFLOW-MODE-DEPTH>$' 1 "$(basename "$(dirname "$skill")") has one opening mode-depth contract"
  assert_count "$skill" '^</WORKFLOW-MODE-DEPTH>$' 1 "$(basename "$(dirname "$skill")") has one closing mode-depth contract"
done

assert_contains "$DEBUG" "Root-cause evidence is mandatory in every mode." "debugging retains root-cause floor"
assert_contains "$DEBUG" '- `lean`: reproduce or inspect the symptom, identify the root cause from' "debugging defines lean evidence path"
assert_contains "$DEBUG" "evidence, make the smallest fix, run the regression check, and inspect the" "debugging lean path retains fix and regression evidence"
assert_contains "$DEBUG" "diff. If evidence does not identify the cause directly, promote to standard." "debugging lean promotes when evidence is insufficient"
assert_contains "$DEBUG" '- `standard`: use an explicit hypothesis-and-test loop, then implement and' "debugging defines standard hypothesis loop"
assert_contains "$DEBUG" '- `strict`: follow all four phases and every existing gate unchanged.' "debugging preserves strict path"
assert_contains "$DEBUG" '- no active mode: invoke `selecting-workflow-mode`.' "debugging selects when mode is absent"
assert_contains "$DEBUG" "Do not reclassify the task here." "debugging does not reclassify"
assert_contains "$DEBUG" "Do not use mode selection to justify guessing or symptom patching." "debugging forbids weakened evidence"
assert_contains "$DEBUG" "In strict mode, you MUST complete each phase before proceeding to the next." "debugging keeps strict phase sequencing"
assert_contains "$DEBUG" 'In standard and lean, the depth contract above determines the required path.' "debugging uses active-mode depth outside strict"
assert_contains "$DEBUG" 'In strict mode, this is mandatory and uses `test-driven-development`.' "debugging preserves strict TDD"
assert_contains "$DEBUG" "In lean mode, a reproducible regression check may be written before or" "debugging allows lean regression timing"
assert_contains "$DEBUG" "after the fix, but it must demonstrate the corrected behavior." "debugging lean still proves corrected behavior"

assert_contains "$VERIFY" "The evidence rule is identical in every mode." "verification iron law is invariant"
assert_contains "$VERIFY" '- `lean`: run the most relevant test or check and inspect the resulting diff.' "verification defines lean breadth"
assert_contains "$VERIFY" '- `standard`: run relevant tests, static checks, and integrated verification.' "verification defines standard breadth"
assert_contains "$VERIFY" '- `strict`: run the complete suite and verify requirements against the written' "verification preserves strict breadth"
assert_contains "$VERIFY" '- no active mode: invoke `selecting-workflow-mode`.' "verification selects when mode is absent"
assert_contains "$VERIFY" "Do not reclassify the task here." "verification does not reclassify"
assert_contains "$VERIFY" "A narrower command must still directly prove the claim being made." "verification keeps claim-proving floor"
assert_contains "$VERIFY" "Execute the mode-appropriate command fresh and completely" "verification gate requires fresh mode-appropriate command"
assert_contains "$VERIFY" "READ: Full output, check exit code, count failures" "verification still requires output and exit-status inspection"
finish
