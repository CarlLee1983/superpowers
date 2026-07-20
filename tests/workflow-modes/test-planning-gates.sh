#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

for skill in brainstorming writing-plans using-git-worktrees test-driven-development; do
  assert_contains "$ROOT/skills/$skill/SKILL.md" "<WORKFLOW-MODE-GATE>" "$skill has a mode gate"
done

assert_contains "$ROOT/skills/brainstorming/SKILL.md" "Standard's inline design is owned by the selector contract" "brainstorming does not hijack standard"
assert_contains "$ROOT/skills/writing-plans/SKILL.md" "durable cross-session handoff" "planning permits standard handoff"
assert_contains "$ROOT/skills/using-git-worktrees/SKILL.md" "materially useful isolation" "worktree is conditional in standard"
assert_contains "$ROOT/skills/test-driven-development/SKILL.md" "new logic or meaningful regression risk" "TDD is risk-selected in standard"
finish
