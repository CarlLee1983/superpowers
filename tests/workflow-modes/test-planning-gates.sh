#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

assert_count() {
  local path="$1" pattern="$2" expected="$3" label="$4" actual
  actual="$(rg -c -- "$pattern" "$path" || true)"
  [[ "$actual" == "$expected" ]] && pass "$label" || fail "$label"
}

for skill in brainstorming writing-plans using-git-worktrees test-driven-development; do
  assert_contains "$ROOT/skills/$skill/SKILL.md" "<WORKFLOW-MODE-GATE>" "$skill has a mode gate"
  assert_count "$ROOT/skills/$skill/SKILL.md" '^<WORKFLOW-MODE-GATE>$' 1 "$skill has one opening mode gate"
  assert_count "$ROOT/skills/$skill/SKILL.md" '^</WORKFLOW-MODE-GATE>$' 1 "$skill has one closing mode gate"
done

brainstorming="$ROOT/skills/brainstorming/SKILL.md"
writing_plans="$ROOT/skills/writing-plans/SKILL.md"
worktrees="$ROOT/skills/using-git-worktrees/SKILL.md"
tdd="$ROOT/skills/test-driven-development/SKILL.md"

assert_contains "$brainstorming" "description: Use when the active workflow mode is strict and the task creates or changes behavior, or when the human partner explicitly requests design exploration" "brainstorming has exact trigger description"
assert_contains "$brainstorming" "If brainstorming was explicitly requested, run the full skill." "brainstorming preserves explicit requests"
assert_contains "$brainstorming" '- `strict`: run the full skill unchanged.' "brainstorming runs fully in strict"
assert_contains "$brainstorming" '- `standard` or `lean`: return control without asking questions or creating a' "brainstorming bypasses in standard and lean"
assert_contains "$brainstorming" "Standard's inline design is owned by the selector contract" "brainstorming does not hijack standard"
assert_contains "$brainstorming" '- no active mode: invoke `selecting-workflow-mode` before continuing.' "brainstorming selects when mode is absent"
assert_contains "$brainstorming" "Do not reclassify the task here." "brainstorming does not reclassify"
assert_contains "$brainstorming" "Approval is only a new user reply sent after the design has been presented." "brainstorming requires post-design user approval"
assert_contains "$brainstorming" 'An initial request to `begin work` or `start work` is not design approval.' "brainstorming rejects initial begin-work approval"
assert_contains "$brainstorming" "Until that approval reply arrives, only read-only project inspection, visible questions, and visible design or options are allowed." "brainstorming limits pre-approval actions"
assert_contains "$brainstorming" "Do not write or commit a spec or plan, create or enter a worktree, invoke a planning or implementation skill, or make project changes before approval." "brainstorming blocks pre-approval artifacts and skills"
assert_contains "$brainstorming" "Follow these steps in order:" "brainstorming preserves ordered checklist flow"
assert_contains "$brainstorming" "Before approval, track steps 1–5 in the visible conversation without creating tool-backed task or todo items." "brainstorming tracks pre-approval steps without task tools"
assert_contains "$brainstorming" "After post-design approval, create tasks for the remaining checklist items and complete them in order." "brainstorming creates remaining tasks only after approval"
assert_not_matches "$brainstorming" 'You MUST create a task for each of these items' "brainstorming removes contradictory pre-approval task mandate"
assert_contains "$brainstorming" "When the user explicitly asks to compare a specific number of options and the existing context is sufficient, present that many named options with trade-offs before asking a clarifying question." "brainstorming answers bounded option requests directly"
assert_contains "$brainstorming" "Keep the project unchanged during that requested comparison." "brainstorming keeps explicit option comparison read-only"
assert_contains "$brainstorming" 'Waiting on your approval before proceeding.' "brainstorming defines canonical declarative approval pause"
assert_contains "$brainstorming" 'After that terminal sentence, do not inspect, read, or take another action.' "brainstorming keeps declarative approval pause terminal"

assert_contains "$writing_plans" "description: Use when strict mode has an approved design, standard mode needs a durable cross-session handoff, or the human partner explicitly requests a written implementation plan" "writing-plans has exact trigger description"
assert_contains "$writing_plans" "Run this skill when explicitly requested." "writing-plans preserves explicit requests"
assert_contains "$writing_plans" '- `strict`: run the full skill.' "writing-plans runs fully in strict"
assert_contains "$writing_plans" '- `standard`: run only for a durable cross-session handoff; inline execution' "writing-plans permits standard durable handoff"
assert_contains "$writing_plans" '- `lean`: return control.' "writing-plans bypasses in lean"
assert_contains "$writing_plans" '- no active mode: invoke `selecting-workflow-mode`.' "writing-plans selects when mode is absent"
assert_contains "$writing_plans" "Do not reclassify the task here." "writing-plans does not reclassify"

assert_contains "$worktrees" "description: Use when strict mode begins implementation, standard mode needs materially useful isolation, or the human partner explicitly requests an isolated workspace" "using-git-worktrees has exact trigger description"
assert_contains "$worktrees" "Run this skill when explicitly requested." "using-git-worktrees preserves explicit requests"
assert_contains "$worktrees" '- `strict`: follow the full isolation workflow.' "using-git-worktrees runs fully in strict"
assert_contains "$worktrees" '- `standard`: continue only when isolation prevents interference, protects' "using-git-worktrees is conditional in standard"
assert_contains "$worktrees" '- `lean`: return control and work in the current workspace.' "using-git-worktrees bypasses in lean"
assert_contains "$worktrees" '- no active mode: invoke `selecting-workflow-mode`.' "using-git-worktrees selects when mode is absent"
assert_contains "$worktrees" "Do not reclassify the task here." "using-git-worktrees does not reclassify"

assert_contains "$tdd" "description: Use when strict mode implements a feature or bugfix, standard mode adds new logic or meaningful regression risk, or the human partner explicitly requests test-first development" "test-driven-development has exact trigger description"
assert_contains "$tdd" "Run this skill when explicitly requested." "test-driven-development preserves explicit requests"
assert_contains "$tdd" '- `strict`: all existing TDD requirements remain mandatory.' "test-driven-development runs fully in strict"
assert_contains "$tdd" '- `standard`: run for new logic or meaningful regression risk.' "test-driven-development is risk-selected in standard"
assert_contains "$tdd" '- `lean`: return control; relevant verification remains mandatory.' "test-driven-development bypasses in lean"
assert_contains "$tdd" '- no active mode: invoke `selecting-workflow-mode`.' "test-driven-development selects when mode is absent"
assert_contains "$tdd" "Do not reclassify the task here." "test-driven-development does not reclassify"
assert_contains "$tdd" "Do not weaken the" "test-driven-development preserves full cycle after selection"
finish
