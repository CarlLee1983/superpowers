# Adaptive Workflow Modes

Add risk-adaptive `lean`, `standard`, and `strict` workflows to Superpowers so capable coding models can avoid unnecessary process on low-risk tasks without weakening verification or the existing full workflow.

## Motivation

Superpowers 6.1.1 applies one complete development workflow to nearly every change: brainstorming, written specification, implementation plan, worktree setup, test-driven development, subagent execution, multiple reviews, and branch finishing. That workflow is valuable for ambiguous or high-risk work, but it adds avoidable turns, artifacts, and context use to small, reversible changes when the primary model can reliably inspect, implement, and verify the work itself.

The fork will select workflow depth from task risk and uncertainty rather than model names. GPT-5.6 Sol, Claude Fable 5, and future models use the same rules. Model capability may improve execution quality, but it does not change the safety characteristics of a payment migration, production data edit, or breaking public API change.

## Goals

- Automatically choose one of three workflow modes for each new user task.
- Let users explicitly force `lean`, `standard`, or `strict`.
- Keep low-risk work continuous and free of mandatory planning artifacts.
- Give medium-risk work a concise design and execution outline without a mandatory approval pause.
- Preserve upstream Superpowers behavior as the `strict` compatibility baseline.
- Require fresh, risk-proportionate verification in every mode.
- Keep mode selection centralized, deterministic, explainable, and independent of model names.
- Minimize the fork's conflict surface when syncing future upstream releases.

## Non-Goals

- Predict model capability from a model identifier.
- Introduce numeric risk scores, telemetry, automatic learning, or per-user behavioral profiling.
- Remove domain-specific skills or platform safety controls.
- Guarantee identical prose across models.
- Redesign the upstream `strict` workflow.

## Chosen Architecture

Create a central `selecting-workflow-mode` skill. `using-superpowers` invokes it at the beginning of each new user task before loading general development-process skills. The selector establishes one active mode and a short reason. Other process skills consume that decision instead of independently classifying the task.

This avoids two rejected designs:

1. **Distributed classification:** letting each skill decide its own mode duplicates policy and can produce contradictory decisions.
2. **Three separate skill packs:** duplicating lean, standard, and strict skills creates maintenance drift and makes mid-task escalation difficult.

The central selector owns classification. Existing skills retain ownership of their specialized workflows and receive a thin mode gate.

## Mode Selection Contract

### Inputs and precedence

The selector evaluates inputs in this order:

1. An explicit user instruction to use `lean`, `standard`, or `strict`
2. Repository instructions such as `AGENTS.md`, `CLAUDE.md`, or equivalent
3. Observable task risk and uncertainty
4. The default mode, `standard`

User and repository instructions follow the host platform's normal instruction precedence. Platform permissions, safety policies, and approval requirements remain outside this workflow and cannot be disabled by a mode.

### Classification

Choose `lean` when all relevant characteristics are low risk:

- The desired result is clear.
- The change is localized and readily reversible.
- The blast radius is small.
- Existing patterns or tests make the correct result easy to verify.
- The task has no material external side effect.

Choose `standard` for bounded work that needs some judgment:

- A normal feature or behavior change spans several components.
- The implementation needs a short design choice or execution outline.
- The impact remains reversible and testable.
- No strict trigger is present.
- The evidence does not clearly distinguish `lean` from `standard`.

Choose `strict` when any material high-risk trigger is present:

- Authentication, authorization, secrets, security boundaries, or vulnerability remediation
- Payments, billing, financial calculations, or regulated behavior
- Production data changes, destructive operations, or data migrations
- Breaking public API or compatibility changes
- Irreversible external actions
- Broad architectural changes with many downstream consumers
- A key unresolved ambiguity that could materially change the result

The matrix is categorical, not additive. File count and changed-line count may provide context but never determine a mode by themselves.

### Declaration and task state

Declare the selection once, before process work:

```text
Mode: standard — multi-component behavior change with bounded impact.
```

The active mode exists in conversation state:

```text
Active workflow mode: standard
Reason: multi-component behavior change with bounded impact
User override: none
```

Do not write mode state into the repository or a temporary file. Re-run selection for a new user task. Continue using the existing selection for follow-ups that remain part of the same task.

A message starts a new task when it requests a materially different outcome from the active task. Corrections, added acceptance criteria, status questions, and implementation follow-ups keep the current mode unless they introduce new risk. When task continuity is genuinely unclear, retain the current mode and re-evaluate risk rather than emitting a second declaration.

### Overrides and escalation

- An explicit user mode is authoritative. If the user forces `lean` for high-risk work, warn briefly and continue in `lean`; do not silently override the user.
- An explicitly requested skill runs even if the current mode would not normally select it. Running that skill does not promote the rest of the task unless the user also requests a higher mode.
- When new scope or risk emerges, announce the reason and promote `lean` to `standard` or `strict`, or `standard` to `strict`.
- Never demote a mode automatically within a task.
- A user may change the mode at any time.

## Workflow Behavior

| Workflow concern | `lean` | `standard` | `strict` |
|---|---|---|---|
| Requirements and design | Understand and act | Give a short inline design and execution outline, then proceed | Full brainstorming with incremental approval |
| Spec and plan files | Do not create | Create only when cross-session handoff or the user requires one | Full written spec, review, and implementation plan |
| Worktree | Not required | Use when isolation is materially useful | Follow upstream workflow |
| TDD | Use when it improves risk control | Use test-first for new logic or meaningful regression risk | Mandatory RED-GREEN-REFACTOR |
| Subagents | Do not use by default | Use only for genuinely independent work when available and permitted | Follow upstream plan and review workflow |
| Review | Inspect the diff and relevant behavior | Perform one integrated self-review | Follow upstream task and quality review stages |
| Verification | Run the most relevant fresh check | Run relevant tests, static checks, and integrated verification | Run the complete upstream completion gate |
| Delivery | Concise result and evidence | Result, important decisions, and evidence | Follow upstream branch-finishing workflow |

### Lean

The lean path is outcome-oriented:

1. Inspect enough context to understand the requested result.
2. Make the smallest appropriate change.
3. Run the most relevant tests or checks.
4. Review the resulting diff.
5. Report the result and fresh verification evidence.

Lean does not require brainstorming, a standalone plan, a worktree, subagents, an independent review, or a failing test written before implementation. It may use any of them when the user explicitly asks or the task develops new risk.

### Standard

The standard path combines design and execution:

1. State a short design and execution outline in commentary.
2. Continue without waiting unless a missing decision would materially alter the result.
3. Implement with test-first development where new logic or regression risk makes it useful.
4. Run relevant tests and static checks.
5. Perform one integrated self-review and deliver evidence.

Standard does not create specification or plan files by default. It may use a worktree or subagents when they provide real isolation or parallelism, but neither is a mandatory ceremony.

### Strict

Strict preserves the upstream 6.1.1 workflow and remains the compatibility baseline:

1. Brainstorm and receive incremental design approval.
2. Write and review the specification.
3. Write and review the implementation plan.
4. Establish the required isolated workspace.
5. Execute with mandatory TDD and the upstream agent/review process.
6. Run the complete verification and branch-finishing workflow.

Only clear duplication or host-platform incompatibility may be corrected in strict mode. Such corrections must not weaken an upstream gate.

## Skill Boundaries

### New files

- `skills/selecting-workflow-mode/SKILL.md` — selection, declaration, override, and escalation contract
- `skills/selecting-workflow-mode/references/risk-matrix.md` — concrete positive, negative, and boundary examples
- `docs/workflow-modes.md` — user-facing mode and override guide
- `tests/workflow-modes/` — static and behavioral mode tests

### Existing skills to update

- `using-superpowers` selects a mode before dispatching general process skills.
- `brainstorming` runs automatically only when strict requires it or the user explicitly requests it.
- `writing-plans` runs automatically only when strict requires it, when standard needs a cross-session handoff, or when the user explicitly requests it.
- `using-git-worktrees` is mandatory in strict, conditional in standard, and opt-in in lean.
- `test-driven-development` is mandatory in strict, risk-selected in standard, and optional in lean.
- `subagent-driven-development`, `executing-plans`, and `dispatching-parallel-agents` follow the mode matrix and host support.
- `requesting-code-review` is mandatory where the strict workflow requires it, conditional in standard, and opt-in in lean.
- `finishing-a-development-branch` follows upstream strict behavior and is otherwise used only when an actual branch lifecycle needs it.
- `systematic-debugging` keeps root-cause evidence in every mode, uses a concise evidence-and-fix loop in lean, a structured hypothesis loop in standard, and the complete upstream process in strict.
- `verification-before-completion` applies in all modes and scales the breadth of evidence without weakening the rule against unsupported completion claims.

`receiving-code-review` remains event-driven rather than mode-driven: review feedback must be evaluated technically whenever it exists.

Each affected skill's frontmatter and body must agree with the selector. Unconditional discovery text such as “MUST use before any creative work” must not reactivate a strict workflow after lean or standard has been selected.

## Domain Skills and Safety

Modes control only general development process. They do not suppress:

- User-requested skills
- Artifact and domain skills for documents, PDFs, databases, API documentation, browser automation, or similar work
- Domain-required render, validation, or safety workflows
- Host permission and approval boundaries
- Applicable legal, privacy, or safety constraints

When a domain skill has a mandatory verification process, that process remains mandatory in every mode.

## Failure Handling

- If the selector cannot distinguish `lean` from `standard`, choose `standard`.
- Do not choose `strict` merely because the task is unfamiliar. Require a concrete strict trigger.
- If no active mode can be found during a process skill invocation, return to the selector before continuing.
- If two skills appear to disagree, the active mode and explicit user instructions resolve the conflict; skills do not reclassify independently.
- If a task changes scope, promote the mode before taking the newly risky action.
- If host capabilities prevent a requested workflow step, follow the existing platform-adaptation behavior and report the limitation.

## Testing Strategy

Tests assert observable behavior rather than exact model prose.

### Static checks

- Validate all skill frontmatter and referenced files.
- Verify every affected process skill contains a compatible mode gate.
- Scan for unconditional instructions that bypass the selector.
- Verify the selector and risk matrix use no model-name allowlist.
- Verify strict-mode instructions still include every upstream-required gate.

### Behavioral scenarios

| Scenario | Required observation |
|---|---|
| Typo, comment, local configuration, or small reversible edit | Select lean; create no spec, plan, worktree, or subagent; run a relevant check |
| Local bug with existing coverage | Select lean; gather root-cause evidence; run the regression test |
| Ordinary feature spanning several components | Select standard; provide one short design and outline; do not wait for approval |
| Authentication, payment, production migration, or breaking API work | Select strict; begin the full upstream workflow |
| Explicit user override | Select the requested mode and declare it once |
| Risk discovered during execution | Announce and promote before risky work |
| Ambiguous low-to-medium boundary | Default to standard |
| Explicit process-skill request in lean | Run that skill without silently promoting the whole task |

Behavioral tests inspect session transcripts and filesystem or git effects. They should check selected skills, approval pauses, artifacts, worktrees, agent dispatch, verification commands, and mode declarations.

### Cross-model acceptance

Run the same scenario set with at least:

- GPT-5.6 Sol
- Claude Fable 5

The prose may differ. Selected mode, required gates, absence of forbidden ceremony, escalation behavior, and verification evidence must agree.

### Regression

- Existing strict-mode skill-triggering tests pass.
- Existing brainstorming, subagent-driven-development, TDD, verification, and finishing tests pass in strict mode.
- Existing platform adaptation tests pass.
- A strict invocation remains behaviorally equivalent to upstream 6.1.1 except for explicit compatibility fixes.

## Success Criteria

- A low-risk lean task completes in one continuous execution with no mandatory planning artifact, subagent, or approval turn.
- A standard task produces at most one mode declaration and one short execution outline before continuing.
- A high-risk automatic classification never selects lean.
- Explicit mode overrides work and are declared once.
- All modes provide fresh verification evidence before claiming completion.
- Strict mode retains the full upstream workflow.
- Mode policy contains no hard-coded model capability list.

## Upstream and Release Strategy

- Base the fork on upstream tag `v6.1.1`.
- Develop on `feature/adaptive-workflow-modes`.
- Do not edit installed plugin cache files.
- Mark the first release with a fork-specific version such as `v6.1.1-adaptive.1`.
- Keep classification in the new selector and keep existing-skill changes thin.
- When syncing upstream, update strict behavior first, then reassess lean and standard gates.
- Install the release independently in Codex and Claude environments before cross-model acceptance testing.
- Document the modes, override syntax, classification examples, and model-independent design in the README.

The first release intentionally excludes scoring, telemetry, learned preferences, and model-name routing. Add those only if behavioral evidence shows the categorical policy is insufficient.
