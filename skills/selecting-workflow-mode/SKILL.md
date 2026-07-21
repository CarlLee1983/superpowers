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

First determine whether the request continues the same task or starts a new one
under Continuity and change below. Re-entry applies only when the selector is invoked again within the same ongoing task, such as after new evidence appears
or debugging reveals materially higher risk.

If an active workflow mode is already present for that ongoing task, this is
re-entry, not task entry. Do not output a new `Mode:` declaration on re-entry.
Apply the override and promotion rules below to the existing state. Skip
task-entry selection and declaration; the already loaded matrix and active state
remain authoritative for this task.

A prior active mode or user override does not make a materially different requested outcome a re-entry.
At that new-task boundary, reset the prior active mode and user override for routing, load the risk matrix, classify the new task, and emit one fresh `Mode:` declaration before task-specific action.

If no active workflow mode is present, follow task-entry selection.

## Task-entry selection

Read [references/risk-matrix.md](references/risk-matrix.md), then select:

- `lean`: clear, localized, reversible, low-impact work
- `standard`: bounded work needing some design judgment
- `strict`: a concrete high-risk trigger is present

After reading the matrix, the next task-specific assistant output is exactly one
declaration line, before any task-specific tool call. Codex's generic bootstrap
narration exception is the exact line defined by `using-superpowers` and ends
when the matrix read completes:

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
the active mode unless they add risk. Starting a new task resets the prior
active mode and user override for routing and follows task-entry selection;
same-task follow-ups may re-enter the selector without a new declaration.

When new risk emerges, announce the reason before promoting the mode.
Never demote automatically. The human partner may change the mode at any time.

## Pre-first-mutation checkpoint

If the task request itself contains a concrete strict trigger under an explicit `lean` or `standard` override, output the warning immediately after the `Mode:` line and before project inspection.
In this branch, the warning is the very next assistant-visible content after the `Mode:` line.
No project tool, discovery, skill announcement, or other prose may precede it.
Keep the explicit mode active; do not emit the canonical promotion line.

After any project inspection, re-evaluate the observed evidence against the
strict triggers. Risk routing and active-mode readiness are separate obligations, not mutually exclusive branches.

First complete risk routing:

- Explicit `lean` or `standard` plus strict evidence: warn about the concrete
  risk and retain the override. An immediate request-text warning fulfills this
  branch unless inspection finds a materially different strict risk. Use
  exactly:
  `Warning: <concrete trigger> is strict-risk work. Retaining your explicit <lean|standard> override.`
  This is a closed two-sentence protocol. Replace only the two placeholders;
  do not paraphrase, prefix, suffix, or merge the warning.
  If inspection finds one materially different trigger, emit the same template
  once more with that distinct trigger. Apart from that one exception, if
  `lean` remains active, emit no assistant prose after the warning and before
  the first mutation. If `standard` remains active, its required inline outline
  is the only additional assistant prose allowed before mutation. Read-only
  inspection tools remain allowed during either interval.
- Automatic `lean` or `standard` plus strict evidence: emit the canonical
  promotion below and pause for approval.
- Active `strict`: follow its strict skills and approval gates without a
  duplicate promotion.
- No strict evidence: retain the active mode.

Then complete readiness for the active mode before mutation:

- Explicit `standard` plus strict evidence: warn, retain `standard`, then complete the standard inline outline before mutation.
- Any other active `standard`: complete the standard inline outline.
- Active `lean`: proceed directly to mutation and verification after any
  required override warning.
- Active `strict`: follow its strict skills and approval gates. A newly
  promoted strict mode remains paused until approval.

If `User override` is `lean` or `standard`, warn without promoting and keep that explicitly chosen mode active.
Continue under that mode unless host safety or permission controls require a pause.
If the active mode is already `strict`, whether selected automatically or explicitly, do not output a promotion.
Canonical promotion requires both `User override: none` and an active mode of `lean` or `standard`.
In that case, output exactly this evidence-backed line, replacing every placeholder:

Keep pre-promotion inspection independently auditable and read-only.
When dedicated Read, Glob, or Grep tools are available, use only those; do not
use a shell command. On platforms where inspection is shell-based, safe closed
read-only discovery may precede literal file reads. A safe discovery command may be standalone `rg --files` or standalone `rg -n`
or `rg --line-number` under this closed grammar:

- For `rg --files`, allow only repeated `-g <glob>` or `--glob <glob>` pairs and project path operands, in any order.
- For `rg -n` or `rg --line-number`, allow only repeated `-g <glob>` or `--glob <glob>` pairs, `--hidden`, `--no-heading`, `--color=never`, and positionals; the allowlisted flags may appear anywhere.
  The first non-option positional must be a non-hyphen search pattern; every later positional is a project path operand.
- The only permitted discovery pipeline is one allowed `rg` discovery command followed by one output-limiting `sed -n` command.
  The output limiter must be exactly `sed -n '<positive-start>[,<positive-end>]p'`; no other `sed` flags, scripts, or operands are allowed.

All other `rg` flags are forbidden here, including command-bearing `--pre` and `--pre-glob`.
Shell parameter expansion (`$name` or `${...}`), backticks, and unquoted brace, tilde, or glob expansion are forbidden.
Regex or glob metacharacters in an `rg` search pattern or `-g`/`--glob` argument must be inside one shell-quoted token.
Use single quotes, or double quotes only when the token contains no shell expansion syntax.
A wildcard `-g` or `--glob` value must be shell-quoted.
Both `rg -n 'amount|payment' .` and `rg -n "amount|payment" .` satisfy this quoting rule.
Do not use shell chaining, pipelines, redirections, command substitution,
command separators, or mix inspection with mutation outside that single closed
exception. Discovery never counts as strict-promotion proof.
For strict-promotion proof, read each exact source and consumer path with its own standalone `cat` or `sed -n` command.

The host has already supplied applicable repository instructions. Do not probe optional instruction files
during this checkpoint. Inspect the user-named source first. For a source and
consumer risk claim, read both the defining file and an actual consuming file.
When the source names a consumer or subsystem, read the likely same-directory
consumer module directly. Do not treat a source comment as proof of a consumer;
the promotion line must cite consumer evidence from a file actually read.
Promotion evidence for each named source and consumer must come from that file's own literal exact-path read.
A wildcard or glob read may discover candidate paths, but it cannot establish consumer identity or count as source or consumer proof.
Safe `rg` discovery has the same limitation.
Do not name a file in the promotion line unless that exact path was read literally and successfully.

`Promoting to strict — inspection found <source> defines <field> consumed by <consumer> as part of <strict surface>; <change> would <consequence>.`

Never output a second `Mode:` line after discovery. Once discovery establishes strict evidence, the next mode-routing content must be the canonical `Promoting to strict — ...` line and its approval pause.

Then pause before the first mutation and ask the human partner whether to
proceed in strict mode. Do not mutate until they answer. Do not output another `Mode:` line:
the promotion line changes the active state. A second `Mode:` line is invalid,
including `Mode: strict — promoted from ...`.

If the active mode remains `standard`, complete its inline design contract
before mutation. In `standard`, after the `Mode:` declaration and any required immediate override warning, output one short inline design and execution outline before the first mutation.
Use exactly this one-line shape:
`Approach: <...>. Files/components: <...>. Verification: <...>.`
Replace the placeholders with the intended approach, affected files or components, and verification strategy.
This is a hard tool boundary: the completed line must precede the first `Write`, `Edit`, or mutating shell/tool call.
A mutation before this line is invalid.
A host bootstrap may require the outline before project inspection; otherwise,
read-only inspection may come before or after it. Output the outline once.
Do not repeat the outline after inspection.
When the host provides dedicated `Read`, `Glob`, or `Grep` tools, use them instead of shell listing for standard inspection.
Continue without an approval pause unless a missing decision would materially alter the result.

An explicitly requested process skill runs without silently promoting the
rest of the task.
