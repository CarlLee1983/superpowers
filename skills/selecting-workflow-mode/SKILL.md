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

After reading the matrix, the next assistant output is exactly one declaration
line, before any task-specific tool call:

`Mode: <lean|standard|strict> — <one-sentence reason>.`

The selector is incomplete until that line is output.

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

When new risk emerges, announce the reason before promoting the mode.
Never demote automatically. The human partner may change the mode at any time.

An explicitly requested process skill runs without silently promoting the
rest of the task.
