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
