---
name: using-superpowers
description: Use when starting any conversation - establishes how to find and use skills, requiring skill invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, ignore this skill.
</SUBAGENT-STOP>

# Using Superpowers

Use relevant skills before acting. User instructions take precedence over
skills, and skills take precedence over default behavior.

## Task entry

For every new user task:

1. Invoke `selecting-workflow-mode`.
2. Declare the selected mode once.
3. Discover domain skills and mode-permitted process skills.
4. Announce each skill when it causes an action or pause.

After the selector returns, the next assistant output is its exact `Mode:`
declaration line. Task entry is incomplete until that line is output.

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
