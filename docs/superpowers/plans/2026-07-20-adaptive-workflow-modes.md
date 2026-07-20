# Adaptive Workflow Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add risk-adaptive `lean`, `standard`, and `strict` workflows to the Superpowers 6.1.1 fork while preserving strict-mode behavior and requiring fresh verification in every mode.

**Architecture:** A new `selecting-workflow-mode` skill is the only classifier. `using-superpowers` selects and declares the active mode before loading general process skills; existing skills receive small mode gates and never classify independently. Static contract tests protect the prose interfaces, while live Claude and Codex sessions validate observable behavior.

**Tech Stack:** Markdown Agent Skills, Bash 3.2-compatible test scripts, `rg`, `jq`, git, Claude Code CLI, Codex CLI.

**Spec:** `docs/superpowers/specs/2026-07-20-adaptive-workflow-modes-design.md`

## Global Constraints

- Base all work on upstream `v6.1.1` in branch `feature/adaptive-workflow-modes`.
- Select modes from task risk and uncertainty; do not use a model-name allowlist.
- Explicit user mode instructions are authoritative; platform safety and approval controls remain authoritative.
- Mode state lives only in the conversation and is declared once per task.
- Automatic mode changes may only promote risk; they may not demote within a task.
- `strict` retains the complete upstream 6.1.1 workflow.
- Every mode retains the rule that completion claims require fresh verification evidence.
- Do not add runtime dependencies, telemetry, scoring, or learned preferences.
- Do not edit files under an installed plugin cache.
- The fork release version is `6.1.1-adaptive.1`.
- Before modifying behavior-shaping skill prose, invoke `superpowers:writing-skills`, read its required TDD background, and record a failing live baseline.

---

## File Map

| Path | Responsibility |
|---|---|
| `skills/selecting-workflow-mode/SKILL.md` | Central mode selection, declaration, override, continuity, and escalation |
| `skills/selecting-workflow-mode/references/risk-matrix.md` | Concrete classification examples and boundaries |
| `skills/using-superpowers/SKILL.md` | Bootstrap that requires selection before process-skill discovery |
| `skills/{brainstorming,writing-plans,using-git-worktrees,test-driven-development}/SKILL.md` | Design, planning, isolation, and TDD gates |
| `skills/{subagent-driven-development,executing-plans,dispatching-parallel-agents,requesting-code-review,finishing-a-development-branch}/SKILL.md` | Execution, review, and delivery gates |
| `skills/{systematic-debugging,verification-before-completion}/SKILL.md` | Mode-proportionate evidence depth |
| `tests/workflow-modes/lib.sh` | Shared static-test assertions |
| `tests/workflow-modes/test-*.sh` | Independent static contracts for each skill family |
| `tests/workflow-modes/run-live-mode-test.sh` | Backend-neutral live acceptance runner |
| `tests/workflow-modes/cases/*.txt` | Live prompts for lean, standard, strict, override, and escalation |
| `docs/workflow-modes.md` | User-facing mode reference |
| `README.md` | Fork workflow overview |
| Version manifests listed in `.version-bump.json` | Fork release identity |

---

### Task 1: Central selector and bootstrap contract

**Files:**
- Create: `tests/workflow-modes/lib.sh`
- Create: `tests/workflow-modes/test-selector-contract.sh`
- Create: `skills/selecting-workflow-mode/SKILL.md`
- Create: `skills/selecting-workflow-mode/references/risk-matrix.md`
- Modify: `skills/using-superpowers/SKILL.md`

**Interfaces:**
- Consumes: direct user instructions, repository instructions, observable task risk, and current conversation continuity.
- Produces: exactly one task-local state with `Active workflow mode`, `Reason`, and `User override`; downstream skills consume this state without reclassification.

- [ ] **Step 1: Record the upstream RED behavior**

Run an unmodified v6.1.1 session against a low-risk typo:

```bash
ROOT="$(pwd)"
BASELINE="/tmp/superpowers-mode-evals/baseline-v6.1.1"
PROJECT="$BASELINE/project"
rm -rf "$BASELINE"
mkdir -p "$PROJECT"
git -C "$PROJECT" init -q -b main
git -C "$PROJECT" config user.name "Mode Eval"
git -C "$PROJECT" config user.email "mode-eval@example.invalid"
printf 'This is teh demo.\n' > "$PROJECT/README.md"
git -C "$PROJECT" add README.md
git -C "$PROJECT" commit -q -m fixture
(
  cd "$PROJECT"
  timeout 300 claude -p \
    'Fix the typo "teh" to "the" in README.md. Make the change and verify it.' \
    --plugin-dir "$ROOT" \
    --model claude-fable-5 \
    --permission-mode bypassPermissions \
    --max-turns 4 \
    --output-format stream-json \
    --verbose > "$BASELINE/transcript.jsonl"
)
rg -i 'brainstorm|design|question|approval' "$BASELINE/transcript.jsonl"
```

Expected: at least one match showing that the unmodified workflow starts
design or approval process for the localized typo. Preserve the transcript at
`/tmp/superpowers-mode-evals/baseline-v6.1.1/transcript.jsonl` for the
before/after report.

- [ ] **Step 2: Add shared static-test assertions**

Create `tests/workflow-modes/lib.sh`:

```bash
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
```

Run:

```bash
chmod +x tests/workflow-modes/lib.sh
bash -n tests/workflow-modes/lib.sh
```

Expected: exit 0.

- [ ] **Step 3: Write the failing selector contract**

Create `tests/workflow-modes/test-selector-contract.sh`:

```bash
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
  assert_contains "$MATRIX" "Default to `standard`" "matrix defines ambiguous default"
  assert_contains "$MATRIX" "Authentication, authorization, or secrets" "matrix defines security trigger"
  assert_contains "$MATRIX" "Production data or data migration" "matrix defines data trigger"
  assert_not_matches "$MATRIX" '\b(gpt|claude|gemini|opus|sonnet|fable)\b' "matrix has no model allowlist"
fi

assert_contains "$BOOTSTRAP" "selecting-workflow-mode" "bootstrap invokes selector first"
assert_contains "$BOOTSTRAP" "Do not invoke a general process skill before a mode is active." "bootstrap enforces routing order"
assert_contains "$BOOTSTRAP" "Explicitly requested skills still run" "bootstrap preserves explicit skill requests"
assert_contains "$BOOTSTRAP" "Domain and artifact skills remain available in every mode." "bootstrap preserves domain skills"
finish
```

Run:

```bash
chmod +x tests/workflow-modes/test-selector-contract.sh
tests/workflow-modes/test-selector-contract.sh
```

Expected: FAIL because the selector and risk matrix do not exist and the bootstrap lacks the routing contract.

- [ ] **Step 4: Create the selector skill**

Create `skills/selecting-workflow-mode/SKILL.md`:

```markdown
---
name: selecting-workflow-mode
description: Use at the start of each new user task, before selecting general development-process skills
---

# Selecting Workflow Mode

Choose workflow depth from task risk, uncertainty, reversibility, blast radius,
and external effects. Never choose from a model name.

## Precedence

1. Explicit user mode instruction
2. Repository instructions
3. Observable task risk
4. Default to `standard`

Explicit user mode instructions are authoritative. Platform safety,
permissions, and approvals remain authoritative outside this workflow.

## Selection

Read [references/risk-matrix.md](references/risk-matrix.md), then select:

- `lean`: clear, localized, reversible, low-impact work
- `standard`: bounded work needing some design judgment
- `strict`: a concrete high-risk trigger is present

Declare exactly once:

`Mode: <lean|standard|strict> — <one-sentence reason>.`

Maintain this conversation state:

```text
Active workflow mode: <lean|standard|strict>
Reason: <one sentence>
User override: <none|lean|standard|strict>
```

Do not write mode state to disk.

## Continuity and change

A materially different requested outcome starts a new task. Corrections,
acceptance criteria, status questions, and implementation follow-ups retain
the active mode unless they add risk.

When new risk emerges, announce the reason before promoting the mode. Never
demote automatically. The human partner may change the mode at any time.

An explicitly requested process skill runs without silently promoting the
rest of the task.
```

- [ ] **Step 5: Create the categorical risk matrix**

Create `skills/selecting-workflow-mode/references/risk-matrix.md`:

```markdown
# Workflow Risk Matrix

Use categorical evidence. File count and changed-line count are context, not
classification rules.

## Lean

Choose `lean` only when the outcome is clear, the change is localized and
readily reversible, the blast radius is small, verification is direct, and
there is no material external side effect.

Examples: typo correction, comment update, local configuration adjustment,
small refactor with existing coverage, localized bug with a reproducible test.

## Standard

Choose `standard` for a normal feature or behavior change spanning several
components, a bounded integration, or work needing a short design choice.
The result must remain reversible and testable, with no strict trigger.

Default to `standard` when evidence does not clearly distinguish lean from
standard. Do not choose strict merely because the task is unfamiliar.

## Strict

Choose `strict` when any material trigger is present:

- Authentication, authorization, or secrets
- Security boundaries or vulnerability remediation
- Payments, billing, finance, or regulated behavior
- Production data or data migration
- Destructive or irreversible external operations
- Breaking public API or compatibility changes
- Broad architecture with many downstream consumers
- A key unresolved ambiguity that could materially change the result

## Overrides

Honor an explicit `lean`, `standard`, or `strict` instruction. If the human
partner forces lean for high-risk work, warn briefly and continue in lean.
Host safety and permission controls still apply.
```

- [ ] **Step 6: Replace the bootstrap with mode-aware discovery**

Keep the existing frontmatter and `<SUBAGENT-STOP>` block in
`skills/using-superpowers/SKILL.md`. Replace the remaining body with:

```markdown
# Using Superpowers

Use relevant skills before acting. User instructions take precedence over
skills, and skills take precedence over default behavior.

## Task entry

For every new user task:

1. Invoke `selecting-workflow-mode`.
2. Declare the selected mode once.
3. Discover domain skills and mode-permitted process skills.
4. Announce each skill when it causes an action or pause.

Do not invoke a general process skill before a mode is active.

## Skill selection

- Domain and artifact skills remain available in every mode.
- Explicitly requested skills still run.
- Process skills must honor their workflow-mode gate.
- If a process skill finds no active mode, return here and select one.
- Skills consume the active mode; they do not classify independently.

Before entering plan mode, invoke brainstorming only when the active mode is
strict or the human partner explicitly requests brainstorming.

## Platform adaptation

- Codex: `references/codex-tools.md`
- Pi: `references/pi-tools.md`
- Antigravity: `references/antigravity-tools.md`

Repository and direct user instructions may override this workflow.
```

- [ ] **Step 7: Run the selector contract**

Run:

```bash
tests/workflow-modes/test-selector-contract.sh
```

Expected: all assertions pass.

- [ ] **Step 8: Commit**

```bash
git add skills/selecting-workflow-mode skills/using-superpowers/SKILL.md tests/workflow-modes
git commit -m "feat: add adaptive workflow mode selector"
```

---

### Task 2: Design, planning, isolation, and TDD gates

**Files:**
- Create: `tests/workflow-modes/test-planning-gates.sh`
- Modify: `skills/brainstorming/SKILL.md`
- Modify: `skills/writing-plans/SKILL.md`
- Modify: `skills/using-git-worktrees/SKILL.md`
- Modify: `skills/test-driven-development/SKILL.md`

**Interfaces:**
- Consumes: `Active workflow mode` from Task 1.
- Produces: strict-only full ideation/planning, conditional standard isolation/TDD, and no automatic lean ceremony.

- [ ] **Step 1: Write the failing planning-gate test**

Create `tests/workflow-modes/test-planning-gates.sh`:

```bash
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
```

Run:

```bash
chmod +x tests/workflow-modes/test-planning-gates.sh
tests/workflow-modes/test-planning-gates.sh
```

Expected: FAIL because the four mode gates are absent.

- [ ] **Step 2: Gate brainstorming**

Change the description to:

```yaml
description: Use when the active workflow mode is strict and the task creates or changes behavior, or when the human partner explicitly requests design exploration
```

Insert after the opening summary:

```markdown
<WORKFLOW-MODE-GATE>
If brainstorming was explicitly requested, run the full skill. Otherwise:

- `strict`: run the full skill unchanged.
- `standard` or `lean`: return control without asking questions or creating a
  spec. Standard's inline design is owned by the selector contract.
- no active mode: invoke `selecting-workflow-mode` before continuing.

Do not reclassify the task here.
</WORKFLOW-MODE-GATE>
```

- [ ] **Step 3: Gate written planning**

Change the description to:

```yaml
description: Use when strict mode has an approved design, standard mode needs a durable cross-session handoff, or the human partner explicitly requests a written implementation plan
```

Insert after the overview:

```markdown
<WORKFLOW-MODE-GATE>
Run this skill when explicitly requested. Otherwise:

- `strict`: run the full skill.
- `standard`: run only for a durable cross-session handoff; inline execution
  outlines do not create a plan file.
- `lean`: return control.
- no active mode: invoke `selecting-workflow-mode`.

Do not reclassify the task here.
</WORKFLOW-MODE-GATE>
```

- [ ] **Step 4: Gate worktree creation**

Change the description to:

```yaml
description: Use when strict mode begins implementation, standard mode needs materially useful isolation, or the human partner explicitly requests an isolated workspace
```

Insert after the overview:

```markdown
<WORKFLOW-MODE-GATE>
Run this skill when explicitly requested. Otherwise:

- `strict`: follow the full isolation workflow.
- `standard`: continue only when isolation prevents interference, protects
  unrelated local changes, or enables independent work.
- `lean`: return control and work in the current workspace.
- no active mode: invoke `selecting-workflow-mode`.

Do not create isolation merely because a task changes multiple files.
</WORKFLOW-MODE-GATE>
```

- [ ] **Step 5: Gate TDD**

Change the description to:

```yaml
description: Use when strict mode implements a feature or bugfix, standard mode adds new logic or meaningful regression risk, or the human partner explicitly requests test-first development
```

Insert before `## When to Use`:

```markdown
<WORKFLOW-MODE-GATE>
Run this skill when explicitly requested. Otherwise:

- `strict`: all existing TDD requirements remain mandatory.
- `standard`: run for new logic or meaningful regression risk.
- `lean`: TDD is optional; relevant verification remains mandatory.
- no active mode: invoke `selecting-workflow-mode`.

When this gate selects TDD, follow the complete skill. Do not weaken the
RED-GREEN-REFACTOR cycle after selecting it.
</WORKFLOW-MODE-GATE>
```

Replace the opening word `Always:` under `## When to Use` with:

```markdown
**When selected by the workflow-mode gate:**
```

- [ ] **Step 6: Run the planning-gate contract**

Run:

```bash
tests/workflow-modes/test-planning-gates.sh
```

Expected: all assertions pass.

- [ ] **Step 7: Commit**

```bash
git add skills/brainstorming/SKILL.md skills/writing-plans/SKILL.md \
  skills/using-git-worktrees/SKILL.md skills/test-driven-development/SKILL.md \
  tests/workflow-modes/test-planning-gates.sh
git commit -m "feat: gate planning workflows by active mode"
```

---

### Task 3: Execution, review, and branch-finishing gates

**Files:**
- Create: `tests/workflow-modes/test-execution-gates.sh`
- Modify: `skills/subagent-driven-development/SKILL.md`
- Modify: `skills/executing-plans/SKILL.md`
- Modify: `skills/dispatching-parallel-agents/SKILL.md`
- Modify: `skills/requesting-code-review/SKILL.md`
- Modify: `skills/finishing-a-development-branch/SKILL.md`

**Interfaces:**
- Consumes: active mode and explicit skill requests.
- Produces: optional standard parallelism/review and strict-compatible execution; lean performs no automatic dispatch or branch menu.

- [ ] **Step 1: Write the failing execution-gate test**

Create `tests/workflow-modes/test-execution-gates.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

for skill in subagent-driven-development executing-plans dispatching-parallel-agents requesting-code-review finishing-a-development-branch; do
  assert_contains "$ROOT/skills/$skill/SKILL.md" "<WORKFLOW-MODE-GATE>" "$skill has a mode gate"
done

assert_contains "$ROOT/skills/subagent-driven-development/SKILL.md" "genuinely independent plan tasks" "SDD standard trigger is bounded"
assert_contains "$ROOT/skills/requesting-code-review/SKILL.md" "one integrated self-review" "standard review is integrated"
assert_contains "$ROOT/skills/finishing-a-development-branch/SKILL.md" "dedicated branch lifecycle" "branch finishing is conditional outside strict"
finish
```

Run:

```bash
chmod +x tests/workflow-modes/test-execution-gates.sh
tests/workflow-modes/test-execution-gates.sh
```

Expected: FAIL because all five gates are absent.

- [ ] **Step 2: Gate plan execution skills**

In `subagent-driven-development`, change the description to:

```yaml
description: Use when the active workflow permits subagents and a written plan has genuinely independent tasks for the current session
```

Insert after the opening paragraph:

```markdown
<WORKFLOW-MODE-GATE>
Run when explicitly requested. Otherwise:

- `strict`: follow the full skill.
- `standard`: run only for genuinely independent plan tasks when subagents are
  available and permitted.
- `lean`: return control; do not dispatch automatically.
- no active mode: invoke `selecting-workflow-mode`.

Do not reclassify the task here.
</WORKFLOW-MODE-GATE>
```

In `executing-plans`, change the description to:

```yaml
description: Use when strict mode executes a written plan in a separate session, or when the human partner explicitly requests inline plan execution
```

Insert after the overview:

```markdown
<WORKFLOW-MODE-GATE>
Run when explicitly requested. Otherwise, run only in `strict`. Standard and
lean execute their current task directly unless a durable written plan was
explicitly selected. If no mode is active, invoke `selecting-workflow-mode`.
</WORKFLOW-MODE-GATE>
```

- [ ] **Step 3: Gate parallel dispatch**

Change the description to:

```yaml
description: Use in standard or strict mode when 2+ independent tasks can run without shared state or sequential dependencies
```

Insert after the overview:

```markdown
<WORKFLOW-MODE-GATE>
- `strict`: follow the skill when its independence conditions hold.
- `standard`: use only when parallelism provides material wall-clock benefit.
- `lean`: return control unless explicitly requested.
- no active mode: invoke `selecting-workflow-mode`.

Host limits and instructions may prohibit subagent dispatch.
</WORKFLOW-MODE-GATE>
```

- [ ] **Step 4: Gate code review**

Change the description to:

```yaml
description: Use when strict mode requires review, standard mode needs independent review for material risk, or the human partner explicitly requests code review
```

Insert after the opening paragraph:

```markdown
<WORKFLOW-MODE-GATE>
Run when explicitly requested. Otherwise:

- `strict`: preserve every existing mandatory review point.
- `standard`: perform one integrated self-review; dispatch an independent
  reviewer only for material risk or broad impact.
- `lean`: inspect the diff directly and return control.
- no active mode: invoke `selecting-workflow-mode`.
</WORKFLOW-MODE-GATE>
```

Replace `Never: Skip review because "it's simple"` in the Red Flags section
with:

```markdown
- Skip a review required by the active mode
```

- [ ] **Step 5: Gate branch finishing**

Change the description to:

```yaml
description: Use when strict mode completes implementation, a dedicated branch lifecycle needs integration, or the human partner explicitly requests merge, PR, or cleanup choices
```

Insert after the overview:

```markdown
<WORKFLOW-MODE-GATE>
Run when explicitly requested. Otherwise:

- `strict`: follow the full skill.
- `standard` or `lean`: continue only when this task created or owns a
  dedicated branch lifecycle; otherwise return a concise handoff without the
  option menu.
- no active mode: invoke `selecting-workflow-mode`.

Verification-before-completion still applies when this skill returns early.
</WORKFLOW-MODE-GATE>
```

- [ ] **Step 6: Run the execution-gate contract**

Run:

```bash
tests/workflow-modes/test-execution-gates.sh
```

Expected: all assertions pass.

- [ ] **Step 7: Commit**

```bash
git add skills/subagent-driven-development/SKILL.md \
  skills/executing-plans/SKILL.md skills/dispatching-parallel-agents/SKILL.md \
  skills/requesting-code-review/SKILL.md \
  skills/finishing-a-development-branch/SKILL.md \
  tests/workflow-modes/test-execution-gates.sh
git commit -m "feat: gate execution and delivery workflows by mode"
```

---

### Task 4: Mode-proportionate debugging and verification

**Files:**
- Create: `tests/workflow-modes/test-evidence-gates.sh`
- Modify: `skills/systematic-debugging/SKILL.md`
- Modify: `skills/verification-before-completion/SKILL.md`

**Interfaces:**
- Consumes: active mode.
- Produces: root-cause evidence in every debugging mode and fresh completion evidence at a breadth appropriate to the mode.

- [ ] **Step 1: Write the failing evidence-gate test**

Create `tests/workflow-modes/test-evidence-gates.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

DEBUG="$ROOT/skills/systematic-debugging/SKILL.md"
VERIFY="$ROOT/skills/verification-before-completion/SKILL.md"
assert_contains "$DEBUG" "<WORKFLOW-MODE-DEPTH>" "debugging defines mode depth"
assert_contains "$DEBUG" "Root-cause evidence is mandatory in every mode." "debugging retains root-cause floor"
assert_contains "$VERIFY" "<WORKFLOW-MODE-DEPTH>" "verification defines mode depth"
assert_contains "$VERIFY" "The evidence rule is identical in every mode." "verification iron law is invariant"
finish
```

Run:

```bash
chmod +x tests/workflow-modes/test-evidence-gates.sh
tests/workflow-modes/test-evidence-gates.sh
```

Expected: FAIL because neither skill defines mode depth.

- [ ] **Step 2: Add debugging depth**

Insert before `## The Iron Law` in `systematic-debugging`:

```markdown
<WORKFLOW-MODE-DEPTH>
Root-cause evidence is mandatory in every mode.

- `lean`: reproduce or inspect the symptom, identify the root cause from
  evidence, make the smallest fix, run the regression check, and inspect the
  diff. If evidence does not identify the cause directly, promote to standard.
- `standard`: use an explicit hypothesis-and-test loop, then implement and
  verify the root-cause fix. The work may stay inline.
- `strict`: follow all four phases and every existing gate unchanged.
- no active mode: invoke `selecting-workflow-mode`.

Do not use mode selection to justify guessing or symptom patching.
</WORKFLOW-MODE-DEPTH>
```

Change `You MUST complete each phase before proceeding to the next.` to:

```markdown
In strict mode, you MUST complete each phase before proceeding to the next.
In standard and lean, the depth contract above determines the required path.
```

In Phase 4 Step 1, replace the unconditional TDD sentence with:

```markdown
   - In strict mode, this is mandatory and uses `test-driven-development`.
   - In standard mode, use test-first for meaningful regression risk.
   - In lean mode, a reproducible regression check may be written before or
     after the fix, but it must demonstrate the corrected behavior.
```

- [ ] **Step 3: Add verification depth**

Insert before `## The Iron Law` in `verification-before-completion`:

```markdown
<WORKFLOW-MODE-DEPTH>
The evidence rule is identical in every mode. Only verification breadth changes:

- `lean`: run the most relevant test or check and inspect the resulting diff.
- `standard`: run relevant tests, static checks, and integrated verification.
- `strict`: run the complete suite and verify requirements against the written
  spec and plan.
- no active mode: invoke `selecting-workflow-mode`.

A narrower command must still directly prove the claim being made.
</WORKFLOW-MODE-DEPTH>
```

In `The Gate Function`, replace `Execute the FULL command` with:

```text
Execute the mode-appropriate command fresh and completely
```

- [ ] **Step 4: Run the evidence contract**

Run:

```bash
tests/workflow-modes/test-evidence-gates.sh
```

Expected: all assertions pass.

- [ ] **Step 5: Commit**

```bash
git add skills/systematic-debugging/SKILL.md \
  skills/verification-before-completion/SKILL.md \
  tests/workflow-modes/test-evidence-gates.sh
git commit -m "feat: scale debugging and verification depth by mode"
```

---

### Task 5: User documentation, static suite, and fork version

**Files:**
- Create: `docs/workflow-modes.md`
- Create: `tests/workflow-modes/run-static-tests.sh`
- Create: `tests/workflow-modes/test-docs-and-version.sh`
- Modify: `README.md`
- Modify: `package.json`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `.cursor-plugin/plugin.json`
- Modify: `.codex-plugin/plugin.json`
- Modify: `.kimi-plugin/plugin.json`
- Modify: `gemini-extension.json`

**Interfaces:**
- Consumes: mode names and guarantees from Tasks 1–4.
- Produces: discoverable user guidance and synchronized `6.1.1-adaptive.1` manifests.

- [ ] **Step 1: Write the failing docs/version test**

Create `tests/workflow-modes/test-docs-and-version.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

DOC="$ROOT/docs/workflow-modes.md"
assert_file "$DOC" "workflow mode guide exists"
if [[ -f "$DOC" ]]; then
  assert_contains "$DOC" "## Lean" "guide documents lean"
  assert_contains "$DOC" "## Standard" "guide documents standard"
  assert_contains "$DOC" "## Strict" "guide documents strict"
  assert_contains "$DOC" "Mode: lean" "guide documents override syntax"
fi
assert_contains "$ROOT/README.md" "Adaptive workflow modes" "README introduces modes"

version_output="$("$ROOT/scripts/bump-version.sh" --check 2>&1)" || {
  printf '%s\n' "$version_output"
  fail "declared versions are synchronized"
}
[[ "$version_output" == *"6.1.1-adaptive.1"* ]] \
  && pass "fork version is adaptive.1" || fail "fork version is adaptive.1"
finish
```

Run:

```bash
chmod +x tests/workflow-modes/test-docs-and-version.sh
tests/workflow-modes/test-docs-and-version.sh
```

Expected: FAIL because the guide and fork version do not exist.

- [ ] **Step 2: Add the user guide**

Create `docs/workflow-modes.md`:

```markdown
# Adaptive workflow modes

Superpowers chooses workflow depth from task risk, uncertainty, reversibility,
blast radius, and external effects. It does not use model names.

Every new task begins with one declaration:

`Mode: lean — localized, reversible change with direct verification.`

Use `Mode: lean`, `Mode: standard`, or `Mode: strict` in your request to
override automatic selection.

## Lean

For clear, localized, reversible work. The agent inspects, changes, runs the
most relevant verification, reviews the diff, and reports evidence. Written
specs, worktrees, strict TDD, subagents, and independent review are optional.

## Standard

For bounded multi-component work. The agent gives a short inline design and
execution outline, then proceeds without an approval pause. It uses test-first
development, isolation, subagents, and independent review only when they
materially control risk.

## Strict

For security, payments, production data, migrations, irreversible operations,
breaking APIs, broad architecture, or material ambiguity. This preserves the
complete upstream Superpowers workflow.

## Guarantees

- Fresh verification evidence is required in every mode.
- Explicit skill requests still run.
- Domain skills and host safety controls remain active.
- The agent may promote a mode when new risk appears, but never demotes it
  automatically within a task.
- A forced lean mode on high-risk work produces a warning but remains lean.
```

- [ ] **Step 3: Update the README workflow description**

Insert before `## The Basic Workflow`:

```markdown
## Adaptive workflow modes

This fork selects process depth from task risk instead of applying the complete
workflow to every change:

- **lean** — direct implementation and focused verification for clear,
  reversible, low-impact work
- **standard** — a short inline design followed by continuous execution for
  bounded multi-component work
- **strict** — the complete upstream workflow for high-risk or materially
  ambiguous work

The agent declares the selected mode once. Override it by including
`Mode: lean`, `Mode: standard`, or `Mode: strict` in the request. See
[`docs/workflow-modes.md`](docs/workflow-modes.md).
```

Rename `## The Basic Workflow` to:

```markdown
## The Strict Workflow
```

Replace the sentence after the numbered workflow:

```markdown
The complete sequence is mandatory in strict mode. Lean and standard use the
reduced contracts described above. Relevant domain skills still apply in every
mode.
```

Replace the Philosophy TDD bullet with:

```markdown
- **Risk-proportionate TDD** - mandatory in strict, selected for meaningful risk in standard, optional in lean
```

- [ ] **Step 4: Synchronize the fork version**

Run:

```bash
scripts/bump-version.sh 6.1.1-adaptive.1
scripts/bump-version.sh --check
```

Expected: all declared manifests report `6.1.1-adaptive.1`.

- [ ] **Step 5: Add the static suite runner**

Create `tests/workflow-modes/run-static-tests.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

for test in \
  test-selector-contract.sh \
  test-planning-gates.sh \
  test-execution-gates.sh \
  test-evidence-gates.sh \
  test-docs-and-version.sh
do
  printf '\n== %s ==\n' "$test"
  "$DIR/$test"
done
```

Run:

```bash
chmod +x tests/workflow-modes/run-static-tests.sh
tests/workflow-modes/run-static-tests.sh
```

Expected: all five scripts pass.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/workflow-modes.md tests/workflow-modes \
  package.json .claude-plugin .cursor-plugin .codex-plugin .kimi-plugin \
  gemini-extension.json
git commit -m "docs: publish adaptive workflow mode contract"
```

---

### Task 6: Live Claude and Codex behavioral acceptance

**Files:**
- Create: `tests/workflow-modes/run-live-mode-test.sh`
- Create: `tests/workflow-modes/cases/lean.txt`
- Create: `tests/workflow-modes/cases/standard.txt`
- Create: `tests/workflow-modes/cases/strict.txt`
- Create: `tests/workflow-modes/cases/override.txt`
- Create: `tests/workflow-modes/cases/escalation.txt`
- Create: `tests/workflow-modes/cases/explicit-skill.txt`

**Interfaces:**
- Consumes: `<backend> <model> <case>` plus `ADAPTIVE_CODEX_HOME` for Codex.
- Produces: JSONL transcript in `/tmp/superpowers-mode-evals/` and pass/fail assertions for mode declaration, approval pauses, artifacts, and escalation.

- [ ] **Step 1: Add exact acceptance prompts**

Create `tests/workflow-modes/cases/lean.txt`:

```text
Fix the typo "teh" to "the" in README.md. Make the change, verify it, and report the evidence.
```

Create `tests/workflow-modes/cases/standard.txt`:

```text
Add a JSON summary command to this small CLI. It must read items.json and print the item count and numeric total. Implement it, add coverage, and verify it.
```

Create `tests/workflow-modes/cases/strict.txt`:

```text
Design a production data migration that converts stored payment amounts from dollars to cents and changes the public payment API. Begin the work.
```

Create `tests/workflow-modes/cases/override.txt`:

```text
Mode: lean. Change the authentication sample so expired tokens are rejected, add a regression check, and verify it.
```

Create `tests/workflow-modes/cases/escalation.txt`:

```text
Rename the amount field in src/schema.js to amountCents and update its consumers. Inspect the repository before changing anything.
```

Create `tests/workflow-modes/cases/explicit-skill.txt`:

```text
Mode: lean. Use the brainstorming skill to explore two possible names for the greeting function. Do not change files yet.
```

- [ ] **Step 2: Create the live runner**

Create `tests/workflow-modes/run-live-mode-test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKEND="${1:?usage: run-live-mode-test.sh <claude|codex> <model> <case>}"
MODEL="${2:?missing model}"
CASE="${3:?missing case}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROMPT_FILE="$ROOT/tests/workflow-modes/cases/$CASE.txt"
OUT_DIR="/tmp/superpowers-mode-evals/$BACKEND/$MODEL/$CASE"
PROJECT="$OUT_DIR/project"
LOG="$OUT_DIR/transcript.jsonl"

rm -rf "$OUT_DIR"
mkdir -p "$PROJECT"
git -C "$PROJECT" init -q -b main
git -C "$PROJECT" config user.name "Mode Eval"
git -C "$PROJECT" config user.email "mode-eval@example.invalid"

case "$CASE" in
  lean)
    printf 'This is teh demo.\n' > "$PROJECT/README.md"
    ;;
  standard)
    mkdir -p "$PROJECT/src" "$PROJECT/test"
    printf '%s\n' '[{"price":2},{"price":3}]' > "$PROJECT/items.json"
    printf '%s\n' '#!/usr/bin/env node' 'console.log("usage: cli summary")' > "$PROJECT/src/cli.js"
    printf '%s\n' '{"scripts":{"test":"node --test"}}' > "$PROJECT/package.json"
    ;;
  strict)
    printf '%s\n' '# payment migration fixture' > "$PROJECT/README.md"
    ;;
  override)
    mkdir -p "$PROJECT/src"
    printf '%s\n' 'export const accepts = token => Boolean(token);' > "$PROJECT/src/auth.js"
    ;;
  escalation)
    mkdir -p "$PROJECT/src"
    printf '%s\n' \
      '// Production payment schema consumed by the public billing API.' \
      'export const payment = { amount: 10 };' > "$PROJECT/src/schema.js"
    ;;
  explicit-skill)
    mkdir -p "$PROJECT/src"
    printf '%s\n' 'export const greet = name => `Hello ${name}`;' > "$PROJECT/src/greeting.js"
    ;;
  *)
    printf 'unknown case: %s\n' "$CASE" >&2
    exit 2
    ;;
esac

git -C "$PROJECT" add .
git -C "$PROJECT" commit -q -m fixture
PROMPT="$(cat "$PROMPT_FILE")"

case "$BACKEND" in
  claude)
    (
      cd "$PROJECT"
      timeout 900 claude -p "$PROMPT" \
        --plugin-dir "$ROOT" \
        --model "$MODEL" \
        --permission-mode bypassPermissions \
        --max-turns 12 \
        --output-format stream-json \
        --verbose > "$LOG"
    )
    ;;
  codex)
    : "${ADAPTIVE_CODEX_HOME:?set ADAPTIVE_CODEX_HOME to a Codex home with this fork installed}"
    timeout 900 env CODEX_HOME="$ADAPTIVE_CODEX_HOME" codex exec \
      --model "$MODEL" \
      --cd "$PROJECT" \
      --sandbox danger-full-access \
      --json \
      "$PROMPT" > "$LOG"
    ;;
  *)
    printf 'unknown backend: %s\n' "$BACKEND" >&2
    exit 2
    ;;
esac

expected="$CASE"
[[ "$CASE" == override ]] && expected=lean
[[ "$CASE" == escalation ]] && expected=strict
[[ "$CASE" == explicit-skill ]] && expected=lean

count="$({ rg -io "Mode: $expected" "$LOG" 2>/dev/null || true; } | wc -l | tr -d ' ')"
[[ "$count" -eq 1 ]] || {
  printf 'expected exactly one Mode: %s declaration; found %s\n' "$expected" "$count"
  exit 1
}

case "$CASE" in
  lean)
    rg -q 'This is the demo' "$PROJECT/README.md"
    [[ ! -e "$PROJECT/docs/superpowers" ]]
    [[ ! -e "$PROJECT/.worktrees" ]]
    ;;
  standard)
    [[ -e "$PROJECT/test" || -e "$PROJECT/tests" ]]
    ! rg -qi 'looks right so far|approve the design|should I continue' "$LOG"
    [[ ! -e "$PROJECT/docs/superpowers/specs" ]]
    ;;
  strict)
    rg -qi 'brainstorm|clarif|question|design' "$LOG"
    ;;
  override)
    rg -qi 'warn|risk|authentication|security' "$LOG"
    ;;
  escalation)
    rg -qi 'promot|escalat|payment|public.*api' "$LOG"
    ;;
  explicit-skill)
    rg -qi 'brainstorming' "$LOG"
    ! rg -qi 'Mode: strict|Mode: standard' "$LOG"
    ;;
esac

printf 'PASS %s %s %s\nLog: %s\n' "$BACKEND" "$MODEL" "$CASE" "$LOG"
```

- [ ] **Step 3: Validate runner syntax**

Run:

```bash
chmod +x tests/workflow-modes/run-live-mode-test.sh
bash -n tests/workflow-modes/run-live-mode-test.sh
```

Expected: exit 0.

- [ ] **Step 4: Run the Claude Fable 5 matrix**

Run:

```bash
for case in lean standard strict override escalation explicit-skill; do
  tests/workflow-modes/run-live-mode-test.sh claude claude-fable-5 "$case"
done
```

Expected: six PASS lines.

- [ ] **Step 5: Run the GPT-5.6 Sol matrix**

Install the local Codex package into a dedicated test `CODEX_HOME`, set
`ADAPTIVE_CODEX_HOME` to that directory, then run:

```bash
for case in lean standard strict override escalation explicit-skill; do
  tests/workflow-modes/run-live-mode-test.sh codex gpt-5.6-sol "$case"
done
```

Expected: six PASS lines. If the local Codex build cannot install a
development plugin non-interactively, perform the install through Codex's
plugin manager once, then rerun the same commands against that dedicated
`CODEX_HOME`.

- [ ] **Step 6: Commit**

```bash
git add tests/workflow-modes/run-live-mode-test.sh tests/workflow-modes/cases
git commit -m "test: add cross-model workflow mode acceptance"
```

---

### Task 7: Full regression, package verification, and release readiness

**Files:**
- Verify only; modify the owning task's files if a regression exposes a defect.

**Interfaces:**
- Consumes: all prior task commits.
- Produces: a clean branch with static contracts, plugin infrastructure tests, strict regressions, live acceptance logs, and a package artifact ready for human review.

- [ ] **Step 1: Run all static mode contracts**

Run:

```bash
tests/workflow-modes/run-static-tests.sh
```

Expected: all assertions pass.

- [ ] **Step 2: Run shell and plugin infrastructure tests**

Run:

```bash
tests/shell-lint/test-lint-shell.sh
tests/claude-code/run-skill-tests.sh
tests/codex/test-marketplace-manifest.sh
tests/codex-plugin-sync/test-sync-to-codex-plugin.sh
tests/codex/test-package-codex-plugin.sh
```

Expected: every command exits 0.

- [ ] **Step 3: Run explicit-skill regressions**

Run:

```bash
tests/explicit-skill-requests/run-test.sh brainstorming \
  tests/explicit-skill-requests/prompts/please-use-brainstorming.txt 4
tests/explicit-skill-requests/run-test.sh systematic-debugging \
  tests/explicit-skill-requests/prompts/use-systematic-debugging.txt 4
```

Expected: both explicitly requested skills are triggered before action.

- [ ] **Step 4: Verify strict compatibility**

Run a strict-mode pass of the existing extended workflows:

```bash
tests/claude-code/run-skill-tests.sh --integration --timeout 1800
```

Expected: existing worktree and subagent-driven-development tests pass with
the complete upstream gates still present.

- [ ] **Step 5: Re-run both live matrices**

Run:

```bash
for case in lean standard strict override escalation explicit-skill; do
  tests/workflow-modes/run-live-mode-test.sh claude claude-fable-5 "$case"
  tests/workflow-modes/run-live-mode-test.sh codex gpt-5.6-sol "$case"
done
```

Expected: twelve PASS lines.

- [ ] **Step 6: Verify diff, version, and package**

Run:

```bash
git diff --check v6.1.1...HEAD
scripts/bump-version.sh --check
git diff --stat v6.1.1...HEAD
scripts/package-codex-plugin.sh --allow-dirty --output /tmp/superpowers-6.1.1-adaptive.1.zip
unzip -p /tmp/superpowers-6.1.1-adaptive.1.zip .codex-plugin/plugin.json \
  | jq -e '.version == "6.1.1-adaptive.1"'
```

Expected: no whitespace errors, synchronized version output, a scoped diff,
successful package creation, and `jq` exit 0.

- [ ] **Step 7: Review requirements against the design**

Run:

```bash
git diff --name-status v6.1.1...HEAD
git log --oneline v6.1.1..HEAD
```

Confirm each design section maps to a committed task:

- selector and categorical matrix
- lean, standard, and strict behavior
- explicit overrides and promotion-only escalation
- domain and safety preservation
- mode-proportionate debugging and verification
- static, strict-regression, and cross-model tests
- documentation and fork version

Expected: no uncovered design requirement and no unrelated file.

- [ ] **Step 8: Present the complete diff for human approval**

Run:

```bash
git diff --stat v6.1.1...HEAD
git diff v6.1.1...HEAD
```

Do not tag, push, publish, or replace the currently installed plugin until the
human partner has reviewed and explicitly approved the complete diff.
