# Adaptive workflow modes

Superpowers chooses workflow depth from task risk, uncertainty, reversibility,
blast radius, and external effects. It does not use model names or a model allowlist.

Every new task begins with one declaration:

`Mode: lean — localized, reversible change with direct verification.`

Use `Mode: lean`, `Mode: standard`, or `Mode: strict` in your request to
override automatic selection.

## Lean

Lean mode is for clear, localized, reversible work. The agent inspects,
changes, runs the most relevant verification, reviews the diff, and reports
evidence. Written specs, worktrees, subagents, and independent review are
optional. Strict TDD is optional in lean mode. Relevant verification remains mandatory.

## Standard

Standard mode is for bounded multi-component work. The agent gives a short
inline design and execution outline, then proceeds without an approval pause.
It uses test-first development, isolation, subagents, and independent review
only when they materially control risk.

## Strict

Strict mode is for security, payments, production data, migrations,
irreversible operations, breaking APIs, broad architecture, or material
ambiguity. It preserves the complete upstream Superpowers workflow.

## Guarantees

- Fresh verification evidence is required in every mode.
- Explicit skill requests still run.
- Domain skills remain active.
- Host and platform safety controls remain active.
- Automatic promotion on newly discovered risk applies only when no explicit
  mode override is active and the current mode is lean or standard.
- An active strict mode is never promoted again.
- An explicitly selected lean or standard mode remains active after newly
  discovered strict risk; the agent warns instead of auto-promoting.
- The agent never demotes a mode automatically within a task.

## Portable declaration protocol

Every newly routed task emits exactly one declaration with this grammar:

`Mode: <lean|standard|strict> — <brief reason>.`

`Mode:` and the lowercase ASCII mode token are protocol tokens. The reason is
non-empty and may use the user's language. The canonical presentation example
is:

`Mode: standard — bounded multi-component change with direct verification.`

The portable hard gate is Mode before mutation or any side effect. A host
profile may allow structurally read-only bootstrap operations first and may
explicitly allow read-only project inspection first. It cannot allow file,
test/build/package, git, subagent-mutation, or external-write events before the
declaration. Validators establish ordering from transcript events and require
`declaration_index < first_mutation_index`; flattened assistant text is not
sufficient evidence.

Runtime policy is model-independent. Mode classification remains centralized
in `selecting-workflow-mode`, uses risk and reversibility rather than a model
name, and is never duplicated in a host adapter.

## Host profiles

- Codex performs three standalone read-only bootstrap reads—`using-superpowers`,
  the selector, and the risk matrix—then declares Mode before project inspection
  and mutation.
- Claude Code and hook-injected hosts treat SessionStart context as transport.
  Mode is the first task-specific visible assistant output, and no project tool
  comes first.
- OpenCode and Pi inject bootstrap text in a user-role message. Duplicate
  injection and reinjection preserve the active task; Mode-before-mutation is
  the portable hard gate.
- Gemini-style instructions-file hosts transport the same tokens and state
  machine. A tool used only to expand an instruction include is a bootstrap
  read, not project inspection. Each include mechanism must be tested to prove
  whether it truly injects content or merely offers an optional read.
- New harnesses document bootstrap transport, skill loading, bootstrap reads,
  read-only and mutating tools, pre-Mode inspection rules, compaction behavior,
  and structural transcript exposure before certification.

Profiles may impose stronger ordering, but they do not choose a mode, invent a
mode, or change override and promotion semantics.

## Conformance and certification

Semantic conformance is release blocking. It checks the selected mode, exactly
one declaration per task, the pre-mutation gate, explicit overrides, task
boundaries, promotion without redeclaration, no automatic demotion, and no
model-name runtime routing. Reason prose is not compared exactly.

Canonical presentation conformance is diagnostic. It records safely
normalizable capitalization, whitespace, dash, terminal-punctuation, and reason
language differences. Shipped skills, examples, documentation, and fixtures
still use the exact canonical presentation.

To certify a new Agent × Model combination:

1. Name the host profile, backend, exact model slug, and plugin version.
2. Run lean, standard, strict, explicit-override, discovered-risk promotion,
   and explicit-process-skill scenarios where the backend permits.
3. Preserve each transcript, selected mode, declaration count, first declaration
   and mutation event indexes, formatting diagnostics, and verification result.
4. Treat an unavailable backend or inaccessible model as NOT RUN, retaining the
   exact failed command instead of recording a pass.

Model slugs belong in test configuration and evidence, never runtime policy.

## Task state and compaction

A same-task continuation reuses the conversation-local active state and does
not emit another declaration. A materially different requested outcome starts
a new task and receives one fresh declaration. Automatic promotion changes the
active state through the canonical `Promoting to strict — ...` event; it never
emits `Mode: strict` as a second declaration and never demotes automatically.
Explicit non-strict overrides remain authoritative and use their existing
warnings.

Mode state is not written to the repository. A compaction or bootstrap
reinjection preserves active task state: transport may be repeated, but a
declaration is repeated only when the requested outcome establishes a real new
task boundary.
