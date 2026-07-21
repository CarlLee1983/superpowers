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

1. Ensure `selecting-workflow-mode` and its risk matrix are loaded. A platform
   bootstrap may mark them already loaded; do not reload them in that case.
2. Declare the selected mode exactly once.
3. Discover domain skills and mode-permitted process skills.
4. Announce each skill when it causes an action or pause.

After the selector returns, the next assistant output is its exact `Mode:`
declaration line. Task entry is incomplete until that line is output.

Do not invoke a general process skill before a mode is active.

On Codex, read this skill alone, then read `selecting-workflow-mode` alone, then read its risk matrix alone.
Use one standalone read-only command for each file. Do not combine those reads with each other or with project inspection.
After the matrix read, output the declaration before any project command or
other tool. Do not read platform references until the mode is active.

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
