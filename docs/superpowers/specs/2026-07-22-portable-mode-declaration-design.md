# Portable Mode Declaration Protocol

## Purpose

Define one model-independent `lean` / `standard` / `strict` state machine that
can cross coding-agent harness boundaries without forcing every harness to use
the same bootstrap envelope, skill loader, or tool order. This release changes
portable declaration semantics only. It does not add an advisory, disabled, or
no-mode route; workflow applicability remains a separate decision.

## Architecture

The design has three layers:

1. **Portable protocol semantics.** The selector owns mode classification,
   declaration, continuity, overrides, promotion, and the pre-mutation gate.
2. **Host-specific transport/profile.** An adapter delivers the selector and
   describes auditable bootstrap and tool events. It never classifies risk.
3. **Transcript validation and conformance tests.** Validators normalize each
   host's native events, classify tool actions structurally, enforce event
   ordering, and separate semantic failures from presentation diagnostics.

The model produces the decision and declaration. Runtime policy does not branch
on model names, slugs, aliases, allowlists, or assumed capability tiers.

## Protocol grammar

Every newly routed task emits exactly one declaration:

`Mode: <lean|standard|strict> — <brief reason>.`

`Mode:` and the mode token are protocol tokens. The canonical mode tokens are
lowercase ASCII: `lean`, `standard`, and `strict`. No fourth token exists.
The reason must be non-empty. The reason may use the human partner's language.
Semantic validators must not compare its exact prose.

Canonical presentation is:

`Mode: standard — bounded multi-component change with direct verification.`

Semantic parsing may trim surrounding whitespace and safely normalize the mode
token. It may tolerate a hyphen in place of the em dash, missing terminal
punctuation, extra whitespace, or a Unicode reason. Those differences produce
presentation diagnostics; they do not by themselves fail semantic conformance.
Repository skill text, examples, documentation, and fixtures use the canonical
grammar exactly.

## Portable ordering and mutation boundary

The declaration must occur before the first mutation or side-effectful operation.
Read-only bootstrap operations may precede it when the active host profile requires them.
Read-only project inspection may precede it only when the host profile explicitly allows that ordering.
Host profiles may impose stricter ordering than the portable hard gate.

Mutation and side effects include:

- file write, edit, delete, apply-patch, create, rename, or removal events;
- shell commands that alter repository or filesystem state;
- test, build, lint, formatter, generator, or package-manager execution because
  those operations can create artifacts, caches, lockfiles, or generated files;
- git staging, commit, branch, worktree, merge, rebase, or push operations;
- PR, release, message, API write, deploy, migration, or other external write;
- subagent work authorized to mutate state.

Structurally read-only events include file reads, glob and grep operations,
repository search, `git status`, `git diff`, `git log`, `git show`, read-only
connector queries, and declared bootstrap reads. Human-readable descriptions
are not sufficient evidence: validators inspect the event type, tool identity,
arguments, command tokens, lifecycle, and host-profile classification.

For each task with a mutation, conformance records and asserts:

```text
declaration_index < first_mutation_index
```

## Shared state machine

Classification remains centralized in `selecting-workflow-mode` and uses risk,
uncertainty, reversibility, blast radius, and external effects. Adapters do not
duplicate the risk matrix. Explicit user overrides are authoritative.

Mode state is conversation-local and is never written to the repository or a
temporary state file. A correction, added acceptance criterion, status request,
implementation follow-up, compaction, or reinjection remains the same task
unless it requests a materially different outcome. A same-task continuation
does not emit another declaration. A materially different requested outcome
starts a new task and emits one fresh declaration.

Automatic state changes only promote; they never demote during a task. The
canonical discovered-risk event remains:

`Promoting to strict — inspection found <source> defines <field> consumed by <consumer> as part of <strict surface>; <change> would <consequence>.`

Promotion updates active state without emitting a second `Mode:` line. An
explicit `lean` or `standard` override remains active when strict risk appears;
the existing canonical warning is emitted instead of an automatic promotion.
Strict mode retains the complete upstream workflow, and fresh verification is
required before completion claims in every mode.

## Host profiles

### Codex

Codex is intentionally stricter than the portable minimum. It performs three
standalone, independently auditable read-only bootstrap operations in order:

1. Read `skills/using-superpowers/SKILL.md` alone.
2. Read `skills/selecting-workflow-mode/SKILL.md` alone.
3. Read `skills/selecting-workflow-mode/references/risk-matrix.md` alone.
4. Emit the canonical Mode declaration.

No project inspection or mutation occurs before the declaration. The three
reads are not combined in this release.

### Claude Code and hook-injected harnesses

SessionStart supplies the bootstrap sources as host context. Host-internal
context injection is not a task-specific tool call. The Mode declaration is the
first task-specific visible assistant output; no project tool or mutation may
precede it. Existing Claude ordering for override warnings, the standard inline
outline, and discovered-risk promotion is preserved.

### OpenCode and Pi

The extension injects bootstrap content into a user-role message. Injected
bootstrap content is transport, not task-specific assistant output. Duplicate
injection, compaction, and reinjection do not start a new task and do not cause
a duplicate Mode declaration. The adapter does not classify risk.

The portable hard gate is Mode before mutation. Mode before project inspection
is preferred where the harness supports visible assistant output before tools;
the profile may explicitly allow structurally read-only inspection first.

### Gemini and instructions-file harnesses

An extension-provided instructions file transports the same protocol tokens and
state machine. Harness include or load behavior does not alter classification.
A tool call used only to expand a declared instruction include is bootstrap
transport, not project inspection, and mutation still requires a prior Mode
declaration.

An include mechanism must be tested with a unique marker. The certification must
establish whether content is injected into context or merely offered as an
optional file read. If expansion is optional, the profile records the resulting
read as bootstrap transport or ships content inline.

## New-host profile contract

Every new harness records:

- bootstrap transport type and its installed delivery surface;
- how skills are loaded or discovered;
- which native events count as bootstrap reads;
- which native tools and argument shapes are read-only;
- which native tools, commands, or lifecycles are mutating;
- whether read-only project inspection can precede visible assistant text;
- how compaction preserves active task state;
- how transcripts expose Mode and mutation ordering.

A new adapter may not invent a mode, duplicate classification, or reclassify
risk. Its profile can strengthen ordering but cannot weaken the shared state
machine or pre-mutation gate.

## Conformance levels

### Semantic conformance — release blocking

A transcript fails for a missing or unknown Mode token, wrong selected mode,
multiple declarations within one task, mutation before declaration, a second
declaration after promotion, automatic demotion, a lost explicit override,
model-name runtime routing, or a same-task continuation treated as a new task.

Validation uses native event indexes and structural event classification. It
does not establish ordering by searching a flattened transcript string.

### Canonical presentation conformance — diagnostic

Formatting diagnostics record noncanonical capitalization, whitespace, dash,
terminal punctuation, or reason language. A live Agent × Model combination does
not fail semantic acceptance solely because one of these safely normalized
presentation differences occurs. Shipped sources and fixtures have no such
diagnostics.

## Agent × Model certification

Certification supplies exact model slugs as test configuration, never runtime
policy. For each live run, preserve backend, exact model slug, plugin version,
transcript path, selected mode, declaration count, declaration event index,
first mutation event index, canonical diagnostics, and verification result.

At minimum, exercise one Codex combination and one non-Codex combination across
lean, standard, strict, explicit override, discovered-risk promotion, and an
explicit process skill. Where credentials permit, run two Codex models. A
missing backend or inaccessible model is `NOT RUN` with its exact failed
command, never `PASS`.
