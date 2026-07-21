---
name: selecting-workflow-mode
description: Use at each new task before general process skills. Read this skill alone, read its risk matrix alone, then output exactly one Mode line before project inspection or mutation.
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

## Entry routes

If an active workflow mode is already present, this is re-entry, not task entry.
Do not output a new `Mode:` declaration on re-entry. Apply the override and promotion rules below to the existing state.
Skip task-entry selection and declaration; the already loaded matrix and active
state remain authoritative for this task.

If no active workflow mode is present, follow task-entry selection.

## Task-entry selection

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

After any project inspection and before the first mutation, re-evaluate the
observed evidence against the strict triggers.

If `User override` is `lean` or `standard`, warn without promoting and keep that explicitly chosen mode active.
Continue under that mode unless host safety or permission controls require a pause.
If the active mode is already `strict`, whether selected automatically or explicitly, do not output a promotion.
Canonical promotion requires both `User override: none` and an active mode of `lean` or `standard`.
In that case, output exactly this evidence-backed line, replacing every placeholder:

Keep pre-promotion inspection independently auditable and read-only.
When dedicated Read, Glob, or Grep tools are available, use only those; do not use a
shell command. On platforms where inspection is shell-based, use only one
standalone `cat` or `sed -n` file read per command. Do not use shell chaining, pipelines, redirections, command substitution,
or mix inspection with mutation.

The host has already supplied applicable repository instructions. Do not probe optional instruction files
during this checkpoint. Inspect the user-named source first. For a source and
consumer risk claim, read both the defining file and an actual consuming file.
When the source names a consumer or subsystem, read the likely same-directory
consumer module directly. Do not treat a source comment as proof of a consumer;
the promotion line must cite consumer evidence from a file actually read.
Promotion evidence for each named source and consumer must come from that file's own literal exact-path read.
A wildcard or glob read may discover candidate paths, but it cannot establish consumer identity or count as source or consumer proof.
Do not name a file in the promotion line unless that exact path was read literally and successfully.

`Promoting to strict — inspection found <source> defines <field> consumed by <consumer> as part of <strict surface>; <change> would <consequence>.`

Then pause before the first mutation and ask the human partner whether to
proceed in strict mode. Do not mutate until they answer. Do not output another `Mode:` line:
the promotion line changes the active state.

If the active mode remains `standard`, complete its inline design contract
before mutation. In `standard`, after project inspection and before the first mutation, output a short inline design and execution outline in a visible inline message.
State the intended approach, files or components involved, and verification
strategy. Continue without an approval pause unless a missing decision would materially alter the result.

An explicitly requested process skill runs without silently promoting the
rest of the task.
