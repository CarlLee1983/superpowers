---
name: using-superpowers
description: Use at every task entry. Codex must read this skill alone, then selecting-workflow-mode alone, then its risk matrix alone in standalone read-only commands; output exactly one Mode line before any project command or other tool.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, ignore this skill.
</SUBAGENT-STOP>

# Using Superpowers

Use relevant skills before acting. User instructions take precedence over
skills, and skills take precedence over default behavior.

## Task entry

For every new user task:

1. Ensure `selecting-workflow-mode` and its risk matrix are loaded.
   On platforms with native skill loading, if they are not already loaded, invoke `selecting-workflow-mode`; it loads its risk matrix before classifying.
   A platform bootstrap may mark both sources already loaded; do not reload them in that case.
   Codex uses the standalone read sequence below instead of native invocation.
2. Declare the selected mode exactly once.
3. If the request itself reveals strict risk under an explicit non-strict
   override, issue the checkpoint warning immediately.
4. Discover domain skills and mode-permitted process skills.
5. Announce each skill when it causes an action or pause.

After the selector returns, the next task-specific assistant output is its exact
`Mode:` declaration line. Task entry is incomplete until that line is output.
Codex may emit one bootstrap narration while loading the three required
sources. If emitted, it must be this exact line and nothing else:

`Loading workflow-selection sources before task analysis.`

Do not invoke a general process skill before a mode is active.

On Codex, read this skill alone, then read `selecting-workflow-mode` alone, then read its risk matrix alone.
The exact second and third paths are `skills/selecting-workflow-mode/SKILL.md`
and `skills/selecting-workflow-mode/references/risk-matrix.md`.
Use one standalone read-only command for each file. Do not combine those reads with each other or with project inspection.
After the matrix read, output the declaration before any project command or
other tool. Do not read platform references until the mode is active.

## Before the first mutation

Complete this checkpoint visibly after the `Mode:` line and before changing
files or external state. If the request itself exposes a concrete strict trigger under an explicit `lean` or `standard` override, warn immediately after the `Mode:` line and before project inspection.
Keep the requested mode active.

After any project inspection, complete risk routing before mutation:

- Explicit `lean` or `standard` plus strict evidence: visibly warn about the
  concrete risk and retain the override. If the immediate warning already
  covered that evidence, do not repeat it. Put the warning and override
  retention in one assistant block. After that block, emit no assistant prose
  before the first mutation; read-only inspection tools may still run.
- Automatic `lean` or `standard` plus strict evidence: output the selector's
  canonical promotion line, then pause for approval without mutating.
- Active `strict`: follow the strict skills and their approval gates without
  emitting a duplicate promotion.

Risk routing does not replace active-mode readiness. If `standard` remains active after routing, including an explicit `standard` override with strict evidence, output a short visible inline outline covering approach, affected files or components, and verification.
If `lean` remains active, proceed directly after any required warning. If
`strict` is active, follow its approval gates. Do not make the first mutation
until both applicable obligations are complete.

## Skill selection

- Domain and artifact skills remain available in every mode.
- Explicitly requested skills still run.
- Process skills must honor their workflow-mode gate.
- If a process skill finds no active mode, return here and select one.
- Skills consume the active mode; they do not classify independently.

Before entering plan mode, invoke brainstorming only when the active mode is
strict or the human partner explicitly requests brainstorming.

## Strict skill discipline

The required `Mode:` declaration remains the first task-specific output. Once
`strict` is active, invoke every relevant skill before any further response or action.
Even a 1% chance that a skill applies means it is relevant. Process skills run before implementation skills.
Follow the selected skill exactly; do not weaken its checklist or gates.

These are strict-mode rationalizations, not reasons to skip a skill:

| Thought | Reality |
|---|---|
| "This is just a simple question" | Questions are tasks. Check for relevant skills. |
| "I need more context first" | Invoke the relevant skill before gathering that context. |
| "Let me explore first" | Relevant process skills govern how exploration happens. |
| "I can check files quickly" | Files lack conversation context. Check for skills first. |
| "This doesn't need a formal skill" | If a skill applies, strict mode requires it. |
| "I remember this skill" | Load the current skill; its contract may have changed. |
| "This doesn't count as a task" | Action is still a task. Check for skills first. |
| "The skill is overkill" | Strict mode intentionally preserves the complete workflow. |
| "I'll just do this one action first" | Skill invocation comes before the action. |
| "This feels productive" | Undisciplined action is not a substitute for the workflow. |
| "I know what that means" | Knowing the concept is not using the current skill. |

In `lean` and `standard`, automatic process-skill use follows the active mode's
gates. Explicitly requested and domain skills still run in every mode.

## Platform adaptation

- Codex: `references/codex-tools.md`
- Pi: `references/pi-tools.md`
- Antigravity: `references/antigravity-tools.md`

Repository and direct user instructions may override this workflow.
