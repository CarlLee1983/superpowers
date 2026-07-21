# Workflow Risk Matrix

Use categorical evidence. File count and changed-line count are context, not
classification rules.

## Lean

Choose `lean` only when the outcome is clear, the change is localized and
readily reversible, the blast radius is small, verification is direct, and
there is no material external side effect.

Examples: typo correction, comment update, local configuration adjustment,
small refactor with existing coverage, localized bug with a reproducible test.

## Standard

Choose `standard` for a normal feature or behavior change spanning several
components, a bounded integration, or work needing a short design choice.
The result must remain reversible and testable, with no strict trigger.

Default to `standard` when evidence does not clearly distinguish lean from
standard. Do not choose strict merely because the task is unfamiliar.
A schema or consumer rename with unknown blast radius starts in `standard`
until inspection establishes whether a strict compatibility surface is present.

## Strict

Choose `strict` when any material trigger is present:

- Authentication, authorization, or secrets
- Security boundaries or vulnerability remediation
- Payments, billing, finance, or regulated behavior
- Production data or data migration
- Destructive or irreversible external operations
- Breaking public API or compatibility changes
- Broad architecture with many downstream consumers
- A key unresolved ambiguity that could materially change the result

## Overrides

Honor an explicit `lean`, `standard`, or `strict` instruction. If the human
partner forces lean for high-risk work, warn briefly and continue in lean.
Host safety and permission controls still apply.

After classifying, return to the selector's completion contract: output its
exact `Mode:` declaration line before any task-specific tool call.
