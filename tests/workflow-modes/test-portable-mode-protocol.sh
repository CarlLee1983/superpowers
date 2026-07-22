#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

DESIGN="$ROOT/docs/superpowers/specs/2026-07-22-portable-mode-declaration-design.md"
SELECTOR="$ROOT/skills/selecting-workflow-mode/SKILL.md"
MATRIX="$ROOT/skills/selecting-workflow-mode/references/risk-matrix.md"
BOOTSTRAP="$ROOT/skills/using-superpowers/SKILL.md"
CODEX_TOOLS="$ROOT/skills/using-superpowers/references/codex-tools.md"
PORTING="$ROOT/docs/porting-to-a-new-harness.md"

assert_file "$DESIGN" "portable Mode declaration design exists"

for file in "$SELECTOR" "$BOOTSTRAP" "$DESIGN"; do
  assert_contains "$file" 'Mode: <lean|standard|strict> — <brief reason>.' \
    "$(basename "$file") defines the canonical portable Mode grammar"
done

assert_contains "$DESIGN" 'The reason may use the human partner'"'"'s language' \
  "portable reasons may use the human partner's language"
assert_contains "$DESIGN" 'reason must be non-empty' \
  "portable reasons must be non-empty"
assert_contains "$DESIGN" 'must not compare its exact prose' \
  "semantic validators do not compare exact reason prose"

assert_contains "$SELECTOR" 'before the first mutation or side-effectful operation' \
  "selector defines the portable pre-mutation hard gate"
assert_contains "$BOOTSTRAP" 'Read-only bootstrap operations may precede the declaration when required by the host profile.' \
  "bootstrap permits profile-declared read-only transport before Mode"
assert_contains "$BOOTSTRAP" 'Read-only project inspection may precede the declaration only when the host profile explicitly allows it.' \
  "bootstrap makes pre-Mode project inspection profile-specific"
assert_contains "$DESIGN" 'Host profiles may impose stricter ordering than the portable hard gate.' \
  "host profiles may impose stricter ordering"

assert_contains "$SELECTOR" 'A host adapter transports the protocol. It does not classify task risk or select a mode.' \
  "selector forbids adapter-owned classification"
assert_contains "$PORTING" 'must not classify task risk or select a mode' \
  "porting guide forbids adapter-owned classification"

RUNTIME_POLICY=(
  "$SELECTOR"
  "$MATRIX"
  "$BOOTSTRAP"
  "$ROOT/hooks/session-start"
  "$ROOT/.opencode/plugins/superpowers.js"
  "$ROOT/.pi/extensions/superpowers.ts"
  "$ROOT/GEMINI.md"
)

runtime_model_routing='(gpt-[0-9]|claude-[0-9]|gemini-[0-9]|MODEL_ALLOWLIST|model_(allowlist|allow_list)|model[^[:cntrl:]]{0,24}(==| in )[^[:cntrl:]]{0,24}(lean|standard|strict))'
runtime_fourth_mode='Mode:[[:space:]]*(advisory|auto|none|off|disabled|bypass)([^[:alpha:]]|$)'
adapter_risk_policy='^[[:space:]]*(if|elif|case|switch)[[:space:](].*(risk|mode|model)|^[[:space:]]*(selected_?mode|active_?mode|task_?risk)[[:space:]]*='

for file in "${RUNTIME_POLICY[@]}"; do
  [[ -f "$file" ]] || continue
  assert_not_matches "$file" "$runtime_model_routing" \
    "${file#"$ROOT/"} has no model-name runtime routing"
  assert_not_matches "$file" "$runtime_fourth_mode" \
    "${file#"$ROOT/"} introduces no fourth Mode token"
done

for adapter in \
  "$ROOT/hooks/session-start" \
  "$ROOT/.opencode/plugins/superpowers.js" \
  "$ROOT/.pi/extensions/superpowers.ts" \
  "$ROOT/GEMINI.md"
do
  [[ -f "$adapter" ]] || continue
  assert_not_matches "$adapter" "$adapter_risk_policy" \
    "${adapter#"$ROOT/"} transports without classifying risk"
done

assert_contains "$SELECTOR" 'Promotion changes the active state without emitting a second `Mode:` declaration.' \
  "promotion never emits a second Mode declaration"
assert_contains "$SELECTOR" 'A same-task continuation must not emit another declaration.' \
  "same-task continuation does not redeclare Mode"
assert_contains "$SELECTOR" 'Mode state is conversation-local and must not be written to disk.' \
  "mode state remains conversation-local"

assert_contains "$CODEX_TOOLS" '1. Read `skills/using-superpowers/SKILL.md` alone.' \
  "Codex profile preserves standalone bootstrap read one"
assert_contains "$CODEX_TOOLS" '2. Read `skills/selecting-workflow-mode/SKILL.md` alone.' \
  "Codex profile preserves standalone bootstrap read two"
assert_contains "$CODEX_TOOLS" '3. Read `skills/selecting-workflow-mode/references/risk-matrix.md` alone.' \
  "Codex profile preserves standalone bootstrap read three"
assert_contains "$CODEX_TOOLS" 'Mode before project inspection and before mutation' \
  "Codex profile remains stricter than the portable minimum"

for metadata in \
  'bootstrap transport type' \
  'how skills are loaded' \
  'bootstrap reads' \
  'read-only tools' \
  'mutating tools or commands' \
  'read-only project inspection' \
  'compaction preserves active task state' \
  'transcripts expose Mode and mutation ordering'
do
  assert_contains "$PORTING" "$metadata" \
    "porting guide defines host-profile metadata: $metadata"
done

assert_contains "$PORTING" 'Host-profile conformance matrix' \
  "porting guide records concrete metadata for every supported harness"
for harness in \
  'Claude Code' \
  'Codex' \
  'Cursor' \
  'Copilot CLI' \
  'OpenCode' \
  'Pi' \
  'Gemini / instructions-file' \
  'Kimi Code' \
  'Antigravity' \
  'Factory Droid'
do
  assert_contains "$PORTING" "| $harness |" \
    "host-profile matrix records $harness"
done

finish
