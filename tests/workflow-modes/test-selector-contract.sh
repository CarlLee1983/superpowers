#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

SELECTOR="$ROOT/skills/selecting-workflow-mode/SKILL.md"
MATRIX="$ROOT/skills/selecting-workflow-mode/references/risk-matrix.md"
BOOTSTRAP="$ROOT/skills/using-superpowers/SKILL.md"
CODEX_TOOLS="$ROOT/skills/using-superpowers/references/codex-tools.md"

assert_file "$SELECTOR" "selector skill exists"
assert_file "$MATRIX" "risk matrix exists"

if [[ -f "$SELECTOR" ]]; then
  assert_contains "$SELECTOR" "Active workflow mode:" "selector defines active mode state"
  assert_contains "$SELECTOR" "Mode: <lean|standard|strict> — <one-sentence reason>." "selector defines one-line declaration"
  assert_contains "$SELECTOR" "Never demote automatically" "selector forbids automatic demotion"
  assert_contains "$SELECTOR" 'Promoting to strict — inspection found <source> defines <field> consumed by <consumer> as part of <strict surface>; <change> would <consequence>.' "selector defines canonical evidence-backed promotion"
  assert_contains "$SELECTOR" "pause before the first mutation" "selector requires a post-inspection pause before mutation"
  assert_contains "$SELECTOR" "Do not use shell chaining, pipelines, redirections, command substitution" "selector requires auditable read-only inspection"
  assert_contains "$SELECTOR" "When dedicated Read, Glob, or Grep tools are available, use only those" "selector prefers structurally read-only inspection tools"
  assert_contains "$SELECTOR" "Do not probe optional instruction files" "selector avoids nonexistent optional instruction probes"
  assert_contains "$SELECTOR" "read both the defining file and an actual consuming file" "selector requires direct source and consumer evidence"
  assert_contains "$SELECTOR" "Do not treat a source comment as proof of a consumer" "selector rejects inferred consumer evidence"
  assert_contains "$SELECTOR" "Promotion evidence for each named source and consumer must come from that file's own literal exact-path read." "selector requires literal exact-path promotion evidence"
  assert_contains "$SELECTOR" "A wildcard or glob read may discover candidate paths, but it cannot establish consumer identity or count as source or consumer proof." "selector limits wildcard reads to discovery"
  assert_contains "$SELECTOR" "Do not name a file in the promotion line unless that exact path was read literally and successfully." "selector forbids fabricated promotion paths"
  assert_contains "$SELECTOR" 'Do not output another `Mode:` line' "selector forbids a second mode declaration during promotion"
  assert_contains "$SELECTOR" "warn without promoting" "selector preserves forced-lean semantics during re-evaluation"
  assert_contains "$SELECTOR" "Explicit user mode instructions are authoritative" "selector honors overrides"
  assert_contains "$SELECTOR" "A materially different requested outcome starts a new task." "selector defines task continuity"
  assert_not_matches "$SELECTOR" '\b(gpt|claude|gemini|opus|sonnet|fable)\b' "selector has no model allowlist"
fi

if [[ -f "$MATRIX" ]]; then
  assert_contains "$MATRIX" 'Default to `standard`' "matrix defines ambiguous default"
  assert_contains "$MATRIX" 'A schema or consumer rename with unknown blast radius starts in `standard`' "matrix keeps unknown rename impact standard until inspection"
  assert_contains "$MATRIX" "Authentication, authorization, or secrets" "matrix defines security trigger"
  assert_contains "$MATRIX" "Production data or data migration" "matrix defines data trigger"
  assert_not_matches "$MATRIX" '\b(gpt|claude|gemini|opus|sonnet|fable)\b' "matrix has no model allowlist"
fi

assert_contains "$BOOTSTRAP" "selecting-workflow-mode" "bootstrap invokes selector first"
assert_contains "$BOOTSTRAP" 'read this skill alone, then read `selecting-workflow-mode` alone, then read its risk matrix alone' "bootstrap defines standalone Codex read sequence"
assert_contains "$BOOTSTRAP" "Do not combine those reads with each other or with project inspection" "bootstrap forbids compound Codex bootstrap reads"
assert_contains "$BOOTSTRAP" "before any project command or other tool" "bootstrap orders declaration before task tools"
assert_contains "$BOOTSTRAP" "Do not invoke a general process skill before a mode is active." "bootstrap enforces routing order"
assert_contains "$BOOTSTRAP" "Explicitly requested skills still run" "bootstrap preserves explicit skill requests"
assert_contains "$BOOTSTRAP" "Domain and artifact skills remain available in every mode." "bootstrap preserves domain skills"
assert_contains "$CODEX_TOOLS" 'using-superpowers/SKILL.md` by itself' "Codex guide starts with standalone bootstrap read"
assert_contains "$CODEX_TOOLS" 'selecting-workflow-mode/SKILL.md` by itself' "Codex guide reads selector separately"
assert_contains "$CODEX_TOOLS" 'risk-matrix.md` by itself' "Codex guide reads matrix separately"
assert_contains "$CODEX_TOOLS" 'Do not use `&&`, `||`, pipes, redirections' "Codex guide bans compound bootstrap commands"
finish
