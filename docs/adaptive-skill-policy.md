# Adaptive skill policy inventory

This inventory is the review map for Adaptive workflow behavior. Runtime
instructions remain in each skill. Update the corresponding focused test
whenever a row changes.

The `strict` column means compatibility with the complete upstream skill unless
the row names a narrower invariant. An explicit skill request runs the skill;
it does not silently promote the rest of the task.

<!-- POLICY-TABLE START -->
| Skill | Lean | Standard | Strict | Explicit request | Invariant tests |
|---|---|---|---|---|---|
| selecting-workflow-mode | Select localized reversible work; declare once; verify directly. | Default when evidence is ambiguous; emit one inline approach before mutation. | Select for a concrete strict trigger and hand off to strict gates. | An explicit mode is authoritative; warn rather than promote an explicit non-strict override. | `test-selector-contract.sh` checks selection, continuity, overrides, promotion, and declaration cardinality. |
| using-superpowers | Load routing first; automatically use only lean-enabled process skills. | Load routing first; process skills consume standard gates. | Preserve complete relevance-first skill discipline after declaration. | Explicit process skills and all domain skills remain available. | `test-selector-contract.sh` checks bootstrap order, routing state, and skill availability. |
| brainstorming | Return control without questions or a spec. | Return control; the selector owns the inline design. | Run the complete collaborative design and approval workflow. | Run the complete skill in any mode. | `test-planning-gates.sh` checks bypass, strict approval, and explicit invocation. |
| writing-plans | Return control and execute directly. | Create a plan only for a durable cross-session handoff. | Create the complete implementation plan. | Create the complete plan in any mode. | `test-planning-gates.sh` checks durable handoff, bypass, and explicit invocation. |
| using-git-worktrees | Work in the current workspace. | Isolate only to prevent interference, protect unrelated changes, or enable independent work. | Follow the complete isolation workflow. | Follow the complete isolation workflow in any mode. | `test-planning-gates.sh` checks conditional isolation, lean bypass, and explicit invocation. |
| test-driven-development | Return control while retaining relevant verification. | Run complete RED-GREEN-REFACTOR for new logic or meaningful regression risk. | Keep all upstream TDD requirements mandatory. | Run complete RED-GREEN-REFACTOR in any mode. | `test-planning-gates.sh` checks selection and the unweakened TDD cycle. |
| subagent-driven-development | Do not dispatch automatically. | Dispatch only genuinely independent plan tasks when agents are available and permitted. | Follow the complete task, review, and final-review workflow. | Run the complete skill subject to host limits. | `test-execution-gates.sh` checks mode routing, independence, and explicit invocation. |
| executing-plans | Execute directly unless a durable written plan was explicitly selected. | Execute directly unless a durable written plan was explicitly selected. | Execute the written plan with checkpoints. | Execute the selected durable plan in any mode. | `test-execution-gates.sh` checks strict selection and direct-execution branches. |
| dispatching-parallel-agents | Do not dispatch automatically. | Dispatch only for material wall-clock benefit and independent work. | Dispatch when the complete independence conditions hold. | Dispatch subject to independence and host constraints. | `test-execution-gates.sh` checks mode gates and host constraints. |
| requesting-code-review | Inspect the diff directly; no automatic independent review. | Perform integrated self-review; add an independent reviewer for material risk or broad impact. | Preserve every upstream mandatory review point. | Perform the requested review in any mode. | `test-execution-gates.sh` checks review depth, diff inspection, and explicit invocation. |
| finishing-a-development-branch | Use the lifecycle only when the task owns a dedicated branch; always verify first. | Use the lifecycle only when the task owns a dedicated branch; always verify first. | Run the complete verification and integration-options workflow. | Run the complete lifecycle for the owned branch. | `test-execution-gates.sh` checks branch ownership, verification, and menu behavior. |
| systematic-debugging | Reproduce, prove root cause, make the smallest fix, run regression, and inspect diff. | Use an explicit hypothesis-and-test loop and verify the root-cause fix. | Follow all four upstream phases and gates. | Run the requested debugging workflow without weakening root-cause evidence. | `test-evidence-gates.sh` checks root cause, raw status, regression, depth, and selector re-entry. |
| verification-before-completion | Run the most relevant claim-proving check and inspect the diff. | Run relevant tests, static checks, and integrated verification. | Run the complete suite and verify the written spec and plan. | Apply the requested breadth while retaining fresh evidence and raw status. | `test-evidence-gates.sh` checks evidence freshness, scope, raw status, and diff inspection. |
<!-- POLICY-TABLE END -->

## Review rule

For an upstream synchronization, compare every changed process skill against
its row independently. Accept upstream body improvements into the strict path,
then reapply only the smallest Adaptive gate needed for lean and standard.
Add a row and focused invariant test before shipping a new process skill.
