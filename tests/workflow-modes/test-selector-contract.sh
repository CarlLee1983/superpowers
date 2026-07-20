#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

SELECTOR="$ROOT/skills/selecting-workflow-mode/SKILL.md"
MATRIX="$ROOT/skills/selecting-workflow-mode/references/risk-matrix.md"
BOOTSTRAP="$ROOT/skills/using-superpowers/SKILL.md"

assert_file "$SELECTOR" "selector skill exists"
assert_file "$MATRIX" "risk matrix exists"

if [[ -f "$SELECTOR" ]]; then
  assert_contains "$SELECTOR" "Active workflow mode:" "selector defines active mode state"
  assert_contains "$SELECTOR" "Mode: <lean|standard|strict> — <one-sentence reason>." "selector defines one-line declaration"
  assert_contains "$SELECTOR" "Never demote automatically" "selector forbids automatic demotion"
  assert_contains "$SELECTOR" "Explicit user mode instructions are authoritative" "selector honors overrides"
  assert_contains "$SELECTOR" "A materially different requested outcome starts a new task." "selector defines task continuity"
  assert_not_matches "$SELECTOR" '\b(gpt|claude|gemini|opus|sonnet|fable)\b' "selector has no model allowlist"
fi

if [[ -f "$MATRIX" ]]; then
  assert_contains "$MATRIX" 'Default to `standard`' "matrix defines ambiguous default"
  assert_contains "$MATRIX" "Authentication, authorization, or secrets" "matrix defines security trigger"
  assert_contains "$MATRIX" "Production data or data migration" "matrix defines data trigger"
  assert_not_matches "$MATRIX" '\b(gpt|claude|gemini|opus|sonnet|fable)\b' "matrix has no model allowlist"
fi

assert_contains "$BOOTSTRAP" "selecting-workflow-mode" "bootstrap invokes selector first"
assert_contains "$BOOTSTRAP" "Do not invoke a general process skill before a mode is active." "bootstrap enforces routing order"
assert_contains "$BOOTSTRAP" "Explicitly requested skills still run" "bootstrap preserves explicit skill requests"
assert_contains "$BOOTSTRAP" "Domain and artifact skills remain available in every mode." "bootstrap preserves domain skills"
finish
