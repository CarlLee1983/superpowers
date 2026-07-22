#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

assert_count() {
  local path="$1" pattern="$2" expected="$3" label="$4" actual
  actual="$(rg -c -- "$pattern" "$path" || true)"
  [[ "$actual" == "$expected" ]] && pass "$label" || fail "$label"
}

for skill in subagent-driven-development executing-plans dispatching-parallel-agents requesting-code-review finishing-a-development-branch; do
  assert_contains "$ROOT/skills/$skill/SKILL.md" "<WORKFLOW-MODE-GATE>" "$skill has a mode gate"
  assert_count "$ROOT/skills/$skill/SKILL.md" '^<WORKFLOW-MODE-GATE>$' 1 "$skill has one opening mode gate"
  assert_count "$ROOT/skills/$skill/SKILL.md" '^</WORKFLOW-MODE-GATE>$' 1 "$skill has one closing mode gate"
done

sdd="$ROOT/skills/subagent-driven-development/SKILL.md"
executing="$ROOT/skills/executing-plans/SKILL.md"
parallel="$ROOT/skills/dispatching-parallel-agents/SKILL.md"
review="$ROOT/skills/requesting-code-review/SKILL.md"
finishing="$ROOT/skills/finishing-a-development-branch/SKILL.md"

assert_contains "$sdd" "description: Use when the active workflow permits subagents and a written plan has genuinely independent tasks for the current session" "SDD has exact trigger description"
assert_contains "$sdd" "Run when explicitly requested. Otherwise:" "SDD preserves explicit requests"
assert_contains "$sdd" '- `strict`: follow the full skill.' "SDD runs fully in strict"
assert_contains "$sdd" '- `standard`: run only for genuinely independent plan tasks when subagents are' "SDD standard trigger is bounded"
assert_contains "$sdd" '- `lean`: return control; do not dispatch automatically.' "SDD bypasses automatic lean dispatch"
assert_contains "$sdd" '- no active mode: invoke `selecting-workflow-mode`.' "SDD selects when mode is absent"
assert_contains "$sdd" "Do not reclassify the task here." "SDD does not reclassify"

assert_contains "$executing" "description: Use when strict mode executes a written plan in a separate session, or when the human partner explicitly requests inline plan execution" "executing-plans has exact trigger description"
assert_contains "$executing" 'Run when explicitly requested. Otherwise, run only in `strict`.' "executing-plans preserves explicit requests"
assert_contains "$executing" "Standard and" "executing-plans has standard branch"
assert_contains "$executing" "lean execute their current task directly unless a durable written plan was" "executing-plans has lean direct-execution branch"
assert_contains "$executing" "explicitly selected." "executing-plans permits explicitly selected durable plans"
assert_contains "$executing" 'If no mode is active, invoke `selecting-workflow-mode`.' "executing-plans selects when mode is absent"

assert_contains "$parallel" "description: Use in standard or strict mode when 2+ independent tasks can run without shared state or sequential dependencies" "parallel dispatch has exact trigger description"
assert_contains "$parallel" '- `strict`: follow the skill when its independence conditions hold.' "parallel dispatch preserves strict behavior"
assert_contains "$parallel" '- `standard`: use only when parallelism provides material wall-clock benefit.' "parallel dispatch is conditional in standard"
assert_contains "$parallel" '- `lean`: return control unless explicitly requested.' "parallel dispatch bypasses lean unless explicit"
assert_contains "$parallel" '- no active mode: invoke `selecting-workflow-mode`.' "parallel dispatch selects when mode is absent"
assert_contains "$parallel" "Host limits and instructions may prohibit subagent dispatch." "parallel dispatch respects host constraints"

assert_contains "$review" "description: Use when strict mode requires review, standard mode needs independent review for material risk, or the human partner explicitly requests code review" "requesting-code-review has exact trigger description"
assert_contains "$review" "Run when explicitly requested. Otherwise:" "requesting-code-review preserves explicit requests"
assert_contains "$review" '- `strict`: preserve every existing mandatory review point.' "requesting-code-review preserves strict review"
assert_contains "$review" '- `standard`: perform one integrated self-review; dispatch an independent' "standard review is integrated"
assert_contains "$review" '- `lean`: inspect the diff directly and return control.' "requesting-code-review bypasses independent lean review"
assert_contains "$review" '- no active mode: invoke `selecting-workflow-mode`.' "requesting-code-review selects when mode is absent"
assert_contains "$review" '- Skip a review required by the active mode' "review red flag follows the active mode"
assert_not_matches "$review" 'Skip review because "it.s simple"' "review no longer requires independent review for every simple change"

assert_contains "$finishing" "description: Use when strict mode completes implementation, a dedicated branch lifecycle needs integration, or the human partner explicitly requests merge, PR, or cleanup choices" "branch finishing has exact trigger description"
assert_contains "$finishing" "Run when explicitly requested. Otherwise:" "branch finishing preserves explicit requests"
assert_contains "$finishing" '- `strict`: follow the full skill.' "branch finishing preserves strict behavior"
assert_contains "$finishing" '- `standard` or `lean`: continue only when this task created or owns a' "branch finishing is conditional outside strict"
assert_contains "$finishing" "dedicated branch lifecycle; otherwise return a concise handoff without the" "branch finishing requires dedicated lifecycle"
assert_contains "$finishing" "option menu." "branch finishing bypasses the menu when returning early"
assert_contains "$finishing" '- no active mode: invoke `selecting-workflow-mode`.' "branch finishing selects when mode is absent"
assert_contains "$finishing" "Verification-before-completion still applies when this skill returns early." "branch finishing preserves verification"
finish
