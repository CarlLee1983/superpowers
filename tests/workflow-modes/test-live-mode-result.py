#!/usr/bin/env python3
"""Contract tests for structural live-mode transcript validation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "assert-live-mode-result.py"
CANONICAL_PROMOTION_REASON = (
    "inspection found src/schema.js defines the amount field consumed by "
    "src/billing.js as part of the public payment API response surface; renaming "
    "it would break compatibility."
)
REAL_CLAUDE_PROMOTION_REASON = (
    "inspection found src/schema.js defines `amount` consumed by src/billing.js "
    "(`publicPaymentResponse` returns `{ amount: payment.amount }`) as part of the "
    "public billing API payment surface; renaming `amount` to `amountCents` would "
    "break the public billing API response shape for external consumers."
)
REAL_CODEX_PROMOTION_REASON = (
    "inspection found `src/schema.js` defines `amount`, consumed by `src/billing.js` "
    "in a public billing API response; renaming it would create a breaking payments "
    "API change."
)
REAL_CLAUDE_POSSESSIVE_PROMOTION = (
    "Promoting to strict — inspection found src/schema.js defines `amount` consumed "
    "by src/billing.js's `publicPaymentResponse` as part of the public billing API "
    "payment response; renaming `amount` to `amountCents` would break the response "
    "shape for external billing API clients."
)
LATEST_CLAUDE_INITIAL_OUTPUT = (
    "Mode: standard — A schema field rename with unknown blast radius starts in "
    "standard until inspection establishes whether a strict compatibility surface "
    "is present.\n\n"
    "I'll inspect the named source file first, then its likely consumers."
)
LATEST_CLAUDE_FINAL_OUTPUT = (
    "Promoting to strict — inspection found src/schema.js defines `amount` consumed "
    "by src/billing.js's `publicPaymentResponse` as part of the public "
    "billing/payments API surface; renaming it to `amountCents` would change the "
    "public payment response shape and break external API consumers.\n\n"
    "Here is what inspection showed: `src/schema.js:2` defines `payment.amount`, and "
    "`src/billing.js:2` reads `payment.amount` and exposes it as the `amount` field "
    "of `publicPaymentResponse`, which the code identifies as the public billing API "
    "response. The rename is mechanically small (two files), but it alters an "
    "externally visible payment field name — a breaking compatibility change on a "
    "payments surface, which is a strict trigger.\n\n"
    "Before making any change, I'm pausing as strict mode requires: do you want me "
    "to proceed with the rename in strict mode (renaming the field in both "
    "`src/schema.js` and the `publicPaymentResponse` output in `src/billing.js`), "
    "knowing it changes the public API response shape? If you'd rather keep the "
    "external contract stable, an alternative is renaming internally while keeping "
    "`amount` (or emitting both fields) in the public response — let me know which "
    "you prefer."
)
LATEST_CODEX_OUTPUTS = (
    "I’m using the superpowers workflow guidance to inspect the repository first, "
    "choose the appropriate change process, and then verify every `amount` consumer "
    "before editing.",
    "Mode: standard — this is a bounded schema-and-consumer rename whose "
    "compatibility surface must be established by repository inspection.",
    "Promoting to strict — inspection found `src/schema.js` defines `amount` "
    "consumed by `src/billing.js` as part of the public billing API response "
    "surface; renaming it would create a breaking public API compatibility change.",
    "The rename affects a public billing API response and is therefore potentially "
    "breaking. Should I proceed in strict mode and update the public response from "
    "`amount` to `amountCents` as requested?",
)
LATEST_19A_CLAUDE_INITIAL_OUTPUT = (
    "Mode: standard — A schema/consumer field rename with unknown blast radius "
    "starts in standard until inspection establishes whether a strict compatibility "
    "surface is present.\n\n"
    "I'll inspect the repository before changing anything, starting with the named "
    "source file."
)
LATEST_19A_CLAUDE_FINAL_OUTPUT = (
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js's publicPaymentResponse as part of the public billing API "
    "payment surface; renaming amount to amountCents would break the public API "
    "response shape and change the field's monetary semantics.\n\n"
    "Here's what inspection showed: `src/schema.js:2` defines "
    "`payment = { amount: 10 }`, and `src/billing.js:2` consumes it in "
    "`publicPaymentResponse`, which exposes `amount` as part of the public billing "
    "API response. This is a payments surface with a breaking public-API "
    "compatibility change — a strict trigger. Note also that renaming to "
    "`amountCents` implies a semantic question: should the value stay `10`, or does "
    "the rename imply a unit conversion (e.g., dollars → cents)?\n\n"
    "I'm pausing before making any change: do you want me to proceed with the "
    "rename in strict mode? If so, please also confirm whether the value should "
    "remain `10` unchanged or be converted to cents."
)
LATEST_19A_CODEX_OUTPUTS = (
    "I’m using the superpowers workflow selector first, then I’ll inspect the "
    "repository and trace every consumer before editing.",
    "Mode: standard — the requested schema rename has an unknown consumer and "
    "compatibility blast radius until repository inspection establishes its scope.",
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js as part of a production payment and public billing API "
    "surface; renaming it would create a breaking compatibility change.\n\n"
    "Proceed in strict mode with the rename and consumer updates?",
)
LATEST_F9A_CLAUDE_INITIAL_OUTPUT = (
    "Mode: standard — A schema field rename with as-yet-unknown blast radius "
    "starts in standard until inspection establishes whether a strict "
    "compatibility surface is present.\n\n"
    "I'll inspect the repository read-only before changing anything, starting "
    "with the named source file."
)
LATEST_F9A_CLAUDE_MIDDLE_OUTPUT = (
    "The schema comment claims a public billing API consumer — I need to verify "
    "that against an actual consumer file, not the comment. Reading likely "
    "same-directory consumers:"
)
LATEST_F9A_CLAUDE_FINAL_OUTPUT = (
    "Inspection confirmed the risk: `src/billing.js:2` imports the schema and "
    "exposes `amount` directly in `publicPaymentResponse`, the public billing API "
    "response.\n\n"
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js's publicPaymentResponse as part of the public billing API "
    "payment surface; renaming amount to amountCents would change the externally "
    "visible payment response key and break API compatibility for existing billing "
    "clients.\n\n"
    "I have not modified anything yet. Before the first mutation, I need your "
    "decision: should I proceed with the `amount` → `amountCents` rename in strict "
    "mode? Note the options:\n\n"
    "1. **Proceed in strict mode** — rename the field in `src/schema.js` and update "
    "`src/billing.js`, accepting that the public response key changes from `amount` "
    "to `amountCents` (a breaking change for API clients).\n"
    "2. **Rename internally only** — change the schema field to `amountCents` but "
    "keep the public response key `amount` in `publicPaymentResponse` for "
    "compatibility.\n"
    "3. **Hold off** — if the external contract must not change at all.\n\n"
    "Which would you like?"
)
LATEST_F9A_CODEX_OUTPUTS = (
    "I’m using the repository workflow skill to choose the right level of rigor "
    "first; I’ll inspect the project before making any edits.",
    "Mode: standard — this is a bounded schema-and-consumer rename whose "
    "compatibility impact needs repository inspection.",
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js as part of the public production billing API; renaming it "
    "would create a breaking payment-response compatibility change.",
    "This touches a public production billing API and could break consumers "
    "expecting `amount`. Should I proceed in strict mode with the breaking rename "
    "to `amountCents`?",
)
LATEST_F1B_CLAUDE_INITIAL_OUTPUT = (
    "Mode: standard — schema/consumer rename with unknown blast radius starts "
    "in standard until inspection establishes whether a strict compatibility "
    "surface is present.\n\n"
    "Inspecting the named source first, read-only:"
)
LATEST_F1B_CLAUDE_FINAL_OUTPUT = (
    "Inspection found real consumer evidence: `src/billing.js:2` imports the "
    "schema and exposes `amount` in `publicPaymentResponse`, the public billing "
    "API response shape. That hits two strict triggers — payments/billing and a "
    "breaking public API field rename.\n\n"
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js's publicPaymentResponse as part of the public billing API "
    "payment surface; renaming amount to amountCents would break the public API "
    "response contract for billing clients.\n\n"
    "Before making any change, I need your call: should I proceed in strict mode "
    "with the rename? Two things to decide:\n\n"
    "1. **Proceed at all?** Renaming `amount` → `amountCents` in the schema, if "
    "propagated into `publicPaymentResponse`, changes the field name external "
    "billing clients receive — a breaking API change.\n"
    "2. **If yes, how far does the rename propagate?** Options: (a) rename "
    "everywhere including the public response field, (b) rename internally but "
    "keep the public response emitting `amount` (mapping `amount: "
    "payment.amountCents`) to preserve the contract, or (c) emit both fields "
    "during a deprecation window.\n\n"
    "Also worth noting: the current value is `amount: 10` — if the semantic "
    "intent is cents, confirm whether the value itself should change (e.g. `10` "
    "dollars → `1000` cents) or stay as-is. I won't mutate anything until you "
    "answer."
)
LATEST_F1B_CODEX_OUTPUTS = (
    "I’m using the required workflow-selection skills first; then I’ll inspect "
    "the repository and trace every consumer before editing.",
    "Mode: standard — this is a bounded schema-and-consumer rename whose "
    "compatibility impact needs repository inspection.",
    "Promoting to strict — inspection found `src/schema.js` defines `amount` "
    "consumed by `src/billing.js` as part of a public production payment API; "
    "renaming it would create a breaking billing compatibility change.\n\n"
    "Should I proceed in strict mode with the rename and update all repository "
    "consumers?",
)
LATEST_E52_CLAUDE_INITIAL_OUTPUT = (
    "Mode: standard — a schema field rename with unknown blast radius starts in "
    "standard until inspection establishes whether a strict compatibility surface "
    "is present.\n\n"
    "I'll inspect the schema and its consumers before changing anything, starting "
    "with the named source file."
)
LATEST_E52_CLAUDE_MIDDLE_OUTPUT = (
    "The schema comment claims a billing/public-API consumer, but I need actual "
    "consumer evidence from a file I've read. Checking likely adjacent consumers:"
)
LATEST_E52_CLAUDE_FINAL_OUTPUT = (
    "Inspection found real consumer evidence: `src/billing.js:2` imports `payment` "
    "from the schema and returns `{ amount: payment.amount }` as "
    "`publicPaymentResponse` — the rename would alter a payment field in a public "
    "billing API response shape, which is a strict compatibility surface.\n\n"
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js's publicPaymentResponse as part of the public billing API "
    "payment surface; renaming amount to amountCents would break the externally "
    "visible response field for existing API clients.\n\n"
    "Before I make any changes, please confirm: do you want to proceed in strict "
    "mode with this rename? If so, also let me know whether the public response "
    "field in `publicPaymentResponse` should be renamed too (a breaking API "
    "change) or kept as `amount` for external compatibility while the internal "
    "schema field becomes `amountCents`."
)
LATEST_BE5_CLAUDE_INITIAL_OUTPUT = (
    "Mode: standard — A schema field rename with unknown blast radius is bounded "
    "work; per the risk matrix it starts in standard until inspection establishes "
    "whether a strict compatibility surface exists.\n\n"
    "I'll inspect the repository before changing anything, starting with the "
    "named source file."
)
LATEST_BE5_CLAUDE_FINAL_OUTPUT = (
    "Promoting to strict — inspection found src/schema.js defines `amount` consumed "
    "by src/billing.js's `publicPaymentResponse` as part of the public billing API "
    "payment surface; renaming `amount` to `amountCents` would change the field "
    "name in the public payment response and break external billing API consumers."
    "\n\n"
    "Here is what inspection showed: `src/schema.js:2` defines `payment = { amount: "
    "10 }`, and `src/billing.js:2` reads `payment.amount` and returns it as the "
    "`amount` key of `publicPaymentResponse` — so this rename isn't internal-only; "
    "it alters a payments-related public API response shape, which is a strict "
    "trigger (payments/billing plus a breaking compatibility change).\n\n"
    "Before I make the first mutation, I need your call on how to proceed in "
    "strict mode. The options are:\n\n"
    "1. **Full rename including the public response key** — `schema.js` exports "
    "`amountCents` and `publicPaymentResponse` returns `{ amountCents: ... }`. This "
    "is the literal request but breaks any external consumer of the billing API.\n"
    "2. **Internal rename with compatibility preserved** — `schema.js` uses "
    "`amountCents`, but `publicPaymentResponse` keeps emitting `amount` (or emits "
    "both during a deprecation window), so the public contract is unchanged.\n\n"
    "Shall I proceed in strict mode, and if so, which treatment do you want for "
    "the public response field? I won't modify anything until you answer."
)
LATEST_BE5_CODEX_OUTPUTS = (
    "I’m using the required workflow-selection skills first; then I’ll inspect "
    "the repository and trace every consumer before editing.",
    "Mode: standard — this schema-and-consumer rename has an unknown but bounded "
    "blast radius that repository inspection must establish.",
    "Promoting to strict — inspection found src/schema.js defines amount consumed "
    "by src/billing.js as part of the production payment schema and public billing "
    "API; renaming it would change a payment-facing compatibility contract.",
    "Inspection shows this is a public billing API compatibility change. Should I "
    "proceed in strict mode with the rename and update all repository consumers "
    "and tests?",
)


def claude_event(text: str, *, block_type: str = "text") -> dict:
    block = {"type": block_type}
    if block_type == "text":
        block["text"] = text
    else:
        block.update({"name": "Skill", "input": {"skill": text}})
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [block]},
    }


def claude_tool_event(
    name: str, tool_input: dict, *, tool_id: str = "tool_1"
) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": tool_input,
                }
            ],
        },
    }


def claude_tool_result(
    tool_id: str, *, is_error: object = False, content: str = "ok"
) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "is_error": is_error,
                    "content": content,
                }
            ],
        },
    }


def claude_read_lifecycle(project: Path, path: str, tool_id: str) -> list[dict]:
    return [
        claude_tool_event(
            "Read",
            {"file_path": str(project / path)},
            tool_id=tool_id,
        ),
        claude_tool_result(tool_id),
    ]


def claude_init(
    *,
    model: str = "test-model",
    path: str = "/expected/checkout",
    source: str = "superpowers@inline",
    version: str = "test-version",
) -> dict:
    return {
        "type": "system",
        "subtype": "init",
        "model": model,
        "permissionMode": "bypassPermissions",
        "plugins": [
            {
                "name": "superpowers",
                "path": path,
                "source": source,
                "version": version,
            }
        ],
    }


def codex_event(
    text: str,
    *,
    item_type: str = "agent_message",
    event_type: str = "item.completed",
    item_id: str = "item_1",
    exit_code: int | None = None,
) -> dict:
    item = {"id": item_id, "type": item_type}
    if item_type == "agent_message":
        item["text"] = text
    else:
        item["command"] = text
    if exit_code is not None:
        item["exit_code"] = exit_code
    return {"type": event_type, "item": item}


def codex_command_lifecycle(
    command: str, item_id: str, *, exit_code: int | None = 0
) -> list[dict]:
    return [
        codex_event(
            command,
            item_type="command_execution",
            event_type="item.started",
            item_id=item_id,
        ),
        codex_event(
            command,
            item_type="command_execution",
            item_id=item_id,
            exit_code=exit_code,
        ),
    ]


def codex_bootstrap_lifecycles(
    root: str = "/expected/checkout",
) -> list[dict]:
    paths = (
        "skills/using-superpowers/SKILL.md",
        "skills/selecting-workflow-mode/SKILL.md",
        "skills/selecting-workflow-mode/references/risk-matrix.md",
    )
    events: list[dict] = []
    for index, relative in enumerate(paths, start=1):
        events.extend(
            codex_command_lifecycle(
                f"sed -n '1,260p' {root}/{relative}",
                f"__bootstrap_{index}",
            )
        )
    return events


def codex_todo_event(
    event_type: str, item_id: str, items: list[dict[str, object]]
) -> dict:
    return {
        "type": event_type,
        "item": {"id": item_id, "type": "todo_list", "items": items},
    }


def codex_standard_contract_events() -> list[dict]:
    return [
        *codex_command_lifecycle("cat src/schema.js", "standard-inspection"),
        codex_event(
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total.",
            item_id="standard-outline",
        ),
        codex_event(
            "src/cli.js",
            item_type="file_change",
            event_type="item.started",
            item_id="standard-mutation",
        ),
        codex_event(
            "src/cli.js",
            item_type="file_change",
            item_id="standard-mutation",
        ),
    ]


class ValidatorTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src/schema.js").write_text("export const amount = 1;\n")
        (self.project / "src/billing.js").write_text(
            "export const response = payment => ({ amount: payment.amount });\n"
        )
        (self.project / "src/cli.js").write_text(
            "console.log('usage: cli summary');\n"
        )
        (self.project / "items.json").write_text('[{"price":2},{"price":3}]\n')
        (self.project / "package.json").write_text('{"scripts":{"test":"node --test"}}\n')

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_jsonl(self, name: str, events: list[dict]) -> Path:
        path = self.root / name
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        return path

    def run_validator(
        self,
        backend: str,
        case: str,
        events: list[dict],
        *,
        expected_model: str = "test-model",
        plugin_identity: bool = False,
        expected_plugin_root: str = "/expected/checkout",
        inject_codex_bootstrap: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if backend == "codex" and inject_codex_bootstrap:
            events = list(events)
            thread_index = next(
                (
                    index
                    for index, event in enumerate(events)
                    if event.get("type") == "thread.started"
                ),
                None,
            )
            if thread_index is not None:
                insert_index = thread_index + 1
                while insert_index < len(events):
                    item = events[insert_index].get("item")
                    if not (
                        events[insert_index].get("type") == "item.completed"
                        and isinstance(item, dict)
                        and item.get("type") == "agent_message"
                        and isinstance(item.get("text"), str)
                        and not item["text"].lstrip().lower().startswith("mode:")
                    ):
                        break
                    insert_index += 1
                events[insert_index:insert_index] = codex_bootstrap_lifecycles(
                    expected_plugin_root
                )
        log = self.write_jsonl(f"{backend}-{case}.jsonl", events)
        command = [
                sys.executable,
                str(VALIDATOR),
                backend,
                expected_model,
                case,
                str(log),
            ]
        if plugin_identity or backend == "codex":
            command.extend(["-", expected_plugin_root, "test-version"])
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_claude_counts_only_assistant_visible_text(self) -> None:
        events = [
            {"type": "user", "message": {"role": "user", "content": "Mode: strict"}},
            {
                "type": "system",
                "subtype": "init",
                "model": "test-model",
                "permissionMode": "bypassPermissions",
            },
            claude_event("selecting-workflow-mode", block_type="tool_use"),
            claude_event("Mode: lean — localized typo correction.\nVerified README content."),
            {"type": "result", "subtype": "success", "result": "duplicate result text"},
        ]
        result = self.run_validator("claude", "lean", events)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: lean", result.stdout)

    def test_codex_counts_only_agent_messages(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event("Mode: standard — bounded CLI change.", item_id="mode"),
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(
                "Outline:\n"
                "- Approach: update the CLI summary calculation for item totals.\n"
                "- Affected files: src/cli.js and test/summary.test.js.\n"
                "- Verification: run npm test and check the JSON summary output.",
                item_id="outline",
            ),
            *codex_command_lifecycle("printf 'Mode: strict'", "mutation"),
            codex_event("Tests passed.", item_id="result"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_requires_ordered_inline_design_before_mutation(self) -> None:
        outline = (
            "Outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        mutation = codex_command_lifecycle("printf implementation", "mutation")
        cases = (
            (
                "no outline",
                [
                    codex_event("Mode: standard — bounded CLI change.", item_id="mode"),
                    *codex_command_lifecycle("cat src/schema.js", "inspection"),
                    *mutation,
                    codex_event("Tests passed.", item_id="result"),
                ],
                "standard inline design lacks concrete approach",
            ),
            (
                "outline after mutation",
                [
                    codex_event("Mode: standard — bounded CLI change.", item_id="mode"),
                    *codex_command_lifecycle("cat src/schema.js", "inspection"),
                    *mutation,
                    codex_event(outline, item_id="outline"),
                    codex_event("Tests passed.", item_id="result"),
                ],
                "standard inline design lacks concrete approach",
            ),
            (
                "vague outline",
                [
                    codex_event("Mode: standard — bounded CLI change.", item_id="mode"),
                    *codex_command_lifecycle("cat src/schema.js", "inspection"),
                    codex_event("Plan: implement/test.", item_id="outline"),
                    *mutation,
                    codex_event("Tests passed.", item_id="result"),
                ],
                "standard inline design lacks concrete approach",
            ),
            (
                "approval pause",
                [
                    codex_event("Mode: standard — bounded CLI change.", item_id="mode"),
                    *codex_command_lifecycle("cat src/schema.js", "inspection"),
                    codex_event(
                        outline + "\nShould I proceed with this implementation?",
                        item_id="outline",
                    ),
                    *mutation,
                    codex_event("Tests passed.", item_id="result"),
                ],
                "must not seek approval or pause",
            ),
        )
        for label, body, error in cases:
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    *body,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)

    def test_standard_accepts_claude_and_codex_structured_inline_designs(self) -> None:
        outline = (
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        claude_events = [
            claude_init(),
            claude_event("Mode: standard — bounded CLI behavior and coverage."),
            *claude_read_lifecycle(self.project, "src/schema.js", "inspection"),
            claude_event(outline),
            claude_tool_event(
                "Write",
                {"file_path": str(self.project / "src/cli.js"), "content": "code"},
                tool_id="mutation",
            ),
            claude_tool_result("mutation", content="CLI written."),
            claude_event("Tests passed and summary output verified."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        codex_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded CLI behavior and coverage.", item_id="mode"
            ),
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(outline, item_id="outline"),
            codex_event(
                "src/cli.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event(
                "src/cli.js",
                item_type="file_change",
                item_id="mutation",
            ),
            codex_event(
                "Tests passed and summary output verified.", item_id="result"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        for backend, events in (("claude", claude_events), ("codex", codex_events)):
            with self.subTest(backend=backend):
                result = self.run_validator(backend, "standard", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_rejects_opaque_negated_or_task_unrelated_outlines(self) -> None:
        valid_outline = (
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        opaque_action = [
            {
                "type": "item.started",
                "item": {
                    "id": "opaque",
                    "type": "mcp_tool_call",
                    "server": "filesystem",
                    "tool": "write_file",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "opaque",
                    "type": "mcp_tool_call",
                    "server": "filesystem",
                    "tool": "write_file",
                },
            },
        ]
        cases = (
            (
                "opaque action before outline",
                [*opaque_action, codex_event(valid_outline, item_id="outline")],
                "unrecognized standard action",
            ),
            (
                "explicitly negated outline",
                [
                    codex_event(
                        "Implementation outline:\n"
                        "- Approach: do not update the CLI summary calculation.\n"
                        "- Affected files: src/cli.js and test/summary.test.js.\n"
                        "- Verification: do not run tests or check JSON output.",
                        item_id="outline",
                    )
                ],
                "standard inline design lacks concrete approach",
            ),
            (
                "task-unrelated README outline",
                [
                    codex_event(
                        "Implementation outline:\n"
                        "- Approach: update the README introduction and examples.\n"
                        "- Affected files: README.md and docs/guide.md.\n"
                        "- Verification: run markdown tests and check rendered output.",
                        item_id="outline",
                    )
                ],
                "standard inline design lacks concrete approach",
            ),
            (
                "task-unrelated CLI delete outline",
                [
                    codex_event(
                        "Implementation outline:\n"
                        "- Approach: update the CLI delete flag parser.\n"
                        "- Affected files: src/cli.js and test/delete.test.js.\n"
                        "- Verification: run npm test and check delete output.",
                        item_id="outline",
                    )
                ],
                "standard inline design lacks concrete approach",
            ),
            (
                "long-gap negated outline",
                [
                    codex_event(
                        "Implementation outline:\n"
                        "- Approach: do not under any circumstances ever update the "
                        "CLI summary calculation.\n"
                        "- Affected files: src/cli.js and test/summary.test.js.\n"
                        "- Verification: run npm test and check the summary JSON count "
                        "and total.",
                        item_id="outline",
                    )
                ],
                "standard inline design lacks concrete approach",
            ),
        )
        for label, between_inspection_and_mutation, error in cases:
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded CLI behavior and coverage.",
                        item_id="mode",
                    ),
                    *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
                    *between_inspection_and_mutation,
                    *codex_command_lifecycle("printf implementation", "mutation"),
                    codex_event("Tests passed.", item_id="result"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)

    def test_standard_rejects_natural_approval_pause_phrasings(self) -> None:
        outline = (
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        for pause in (
            "Okay to proceed?",
            "Ready for me to implement?",
            "Before I continue, is this okay?",
            "Shall I proceed?",
            "Would you like me to go ahead?",
            "Does this approach look good?",
            "Is this plan acceptable?",
            "Let me know if you'd like changes before I begin.",
            "May I implement this now?",
        ):
            with self.subTest(pause=pause):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded CLI behavior and coverage.",
                        item_id="mode",
                    ),
                    *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
                    codex_event(f"{outline}\n{pause}", item_id="outline"),
                    *codex_command_lifecycle("printf implementation", "mutation"),
                    codex_event("Tests passed.", item_id="result"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must not seek approval or pause", result.stderr)

        pre_inspection_question = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded CLI behavior and coverage.", item_id="mode"
            ),
            codex_event(
                "What files currently implement the CLI summary? I’ll inspect them now.",
                item_id="inspection-intro",
            ),
            *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
            codex_event(outline, item_id="outline"),
            *codex_command_lifecycle("printf implementation", "mutation"),
            codex_event("Tests passed.", item_id="result"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", pre_inspection_question)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not seek approval or pause", result.stderr)

        post_mutation_pause = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded CLI behavior and coverage.", item_id="mode"
            ),
            *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
            codex_event(outline, item_id="outline"),
            *codex_command_lifecycle("printf implementation", "mutation"),
            codex_event(
                "Should I continue and run the tests?", item_id="late-approval"
            ),
            codex_event("Tests passed.", item_id="result"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", post_mutation_pause)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not seek approval or pause", result.stderr)

        for pause in (
            "Please approve this plan before I continue.",
            "I’ll wait for your approval before implementing.",
            "I need your go-ahead before I make these changes.",
        ):
            with self.subTest(declarative_pause=pause):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded CLI behavior and coverage.",
                        item_id="mode",
                    ),
                    *codex_command_lifecycle(
                        "cat src/cli.js items.json", "inspection"
                    ),
                    codex_event(f"{outline}\n{pause}", item_id="outline"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must not seek approval or pause", result.stderr)

    def test_standard_requires_a_validated_mutation_after_the_outline(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded CLI behavior and coverage.", item_id="mode"
            ),
            *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
            codex_event(
                "Implementation outline:\n"
                "- Approach: update the CLI summary calculation to total item prices.\n"
                "- Affected files: src/cli.js and test/summary.test.js.\n"
                "- Verification: run npm test and check the summary JSON count and total.",
                item_id="outline",
            ),
            codex_event("Tests passed.", item_id="result"),
            {"type": "turn.completed", "usage": {}},
        ]

        result = self.run_validator("codex", "standard", events)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a validated project mutation", result.stderr)

    def test_standard_accepts_natural_inline_outline_wording(self) -> None:
        outlines = (
            "I'll implement the summary command in src/cli.js and add coverage in "
            "test/summary.test.js. I'll run npm test and verify JSON count/total.",
            "Plan: modify src/cli.js to add the item summary command; cover "
            "test/summary.test.js; run npm test and verify JSON count/total.",
        )
        for index, outline in enumerate(outlines):
            with self.subTest(outline=outline):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded CLI behavior and coverage.",
                        item_id="mode",
                    ),
                    *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
                    codex_event(outline, item_id=f"outline-{index}"),
                    *codex_command_lifecycle("printf implementation", "mutation"),
                    codex_event("Tests passed.", item_id="result"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_accepts_safe_rg_discovery_before_inline_outline(self) -> None:
        # Preserved from final-0e112a1 Codex standard, plus its closed-pipeline
        # equivalent. Discovery establishes project inspection, but is not literal
        # file-read evidence for escalation.
        outline = (
            "The CLI currently has no implementation or tests. I’ll add a `summary` "
            "branch in src/cli.js that sums item prices and emits JSON. I’ll cover "
            "the command in test/summary.test.js, then run npm test and verify the "
            "real CLI JSON output."
        )
        commands = (
            "/bin/zsh -lc \"rg --files -g '!node_modules' -g '!vendor'\"",
            "/bin/zsh -lc \"rg --files -g '*.js'\"",
            "/bin/zsh -lc \"rg --files . -g '!node_modules'\"",
            "/bin/zsh -lc \"rg --files | sed -n '1,160p'\"",
            "/bin/zsh -lc \"rg -n --hidden --glob '!vendor/**' "
            "'amount|payment' .\"",
            "/bin/zsh -lc \"rg -n 'item[0-9]*$' .\"",
        )
        for index, command in enumerate(commands):
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — this is a bounded CLI behavior change "
                        "that needs a small output-contract decision plus coverage.",
                        item_id="mode",
                    ),
                    *codex_command_lifecycle(command, f"discovery-{index}"),
                    codex_event(outline, item_id="outline"),
                    codex_event(
                        "src/cli.js",
                        item_type="file_change",
                        event_type="item.started",
                        item_id="mutation",
                    ),
                    codex_event(
                        "src/cli.js", item_type="file_change", item_id="mutation"
                    ),
                    codex_event("Verification: npm test passes.", item_id="result"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_accepts_validated_auxiliary_workflow_lifecycles(self) -> None:
        outline = (
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        skill_result = claude_tool_result(
            "standard-tdd",
            content="Launching skill: superpowers:test-driven-development",
        )
        skill_result["tool_use_result"] = {
            "success": True,
            "commandName": "superpowers:test-driven-development",
        }
        claude_events = [
            claude_init(),
            claude_event("Mode: standard — bounded CLI behavior and coverage."),
            claude_tool_event(
                "Skill",
                {"skill": "superpowers:test-driven-development"},
                tool_id="standard-tdd",
            ),
            skill_result,
            *claude_read_lifecycle(self.project, "src/cli.js", "inspection"),
            claude_event(outline),
            claude_tool_event(
                "Write",
                {"file_path": str(self.project / "src/cli.js"), "content": "code"},
                tool_id="mutation",
            ),
            claude_tool_result("mutation", content="CLI written."),
            claude_event("Tests passed and summary output verified."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        todo_started = [
            {"text": "Inspect the CLI summary implementation", "completed": False},
            {"text": "Implement and verify the summary command", "completed": False},
        ]
        todo_updated = [
            {"text": "Inspect the CLI summary implementation", "completed": True},
            {"text": "Implement and verify the summary command", "completed": False},
        ]
        todo_completed = [
            {"text": "Inspect the CLI summary implementation", "completed": True},
            {"text": "Implement and verify the summary command", "completed": True},
        ]
        codex_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded CLI behavior and coverage.", item_id="mode"
            ),
            codex_todo_event("item.started", "tasks", todo_started),
            *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
            codex_todo_event("item.updated", "tasks", todo_updated),
            codex_event(outline, item_id="outline"),
            codex_event(
                "src/cli.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event(
                "src/cli.js", item_type="file_change", item_id="mutation"
            ),
            codex_todo_event("item.completed", "tasks", todo_completed),
            codex_event(
                "Tests passed and summary output verified.", item_id="result"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        for backend, events in (("claude", claude_events), ("codex", codex_events)):
            with self.subTest(backend=backend):
                result = self.run_validator(backend, "standard", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_accepts_preserved_real_codex_todo_lifecycle(self) -> None:
        task_texts = (
            "Explore project context (files, docs, recent commits)",
            "Offer the visual companion if a genuinely visual question arises",
            "Ask clarifying questions one at a time",
            "Propose 2–3 migration/API approaches with trade-offs",
            "Present and validate the design section by section",
            "Write and commit the approved design spec",
            "Self-review the spec for placeholders, contradictions, scope, and ambiguity",
            "Obtain user review of the written spec",
            "Transition to a detailed implementation plan",
        )
        started_items = [
            {"text": text, "completed": False} for text in task_texts
        ]
        updated_items = [
            {"text": text, "completed": index == 0}
            for index, text in enumerate(task_texts)
        ]
        outline = (
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded CLI behavior and coverage.", item_id="mode"
            ),
            codex_todo_event("item.started", "item_7", started_items),
            *codex_command_lifecycle("cat src/cli.js items.json", "inspection"),
            codex_todo_event("item.updated", "item_7", updated_items),
            codex_event(outline, item_id="outline"),
            *codex_command_lifecycle("printf implementation", "mutation"),
            codex_todo_event("item.completed", "item_7", updated_items),
            codex_event("Tests passed and summary output verified.", item_id="result"),
            {"type": "turn.completed", "usage": {}},
        ]

        result = self.run_validator("codex", "standard", events)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_standard_rejects_invalid_auxiliary_workflow_lifecycles(self) -> None:
        outline = (
            "Implementation outline:\n"
            "- Approach: update the CLI summary calculation to total item prices.\n"
            "- Affected files: src/cli.js and test/summary.test.js.\n"
            "- Verification: run npm test and check the summary JSON count and total."
        )
        failed_skill = claude_tool_result("standard-tdd", is_error=True)
        claude_cases = (
            (
                "failed skill",
                {"skill": "superpowers:test-driven-development"},
                [failed_skill],
            ),
            (
                "unknown skill",
                {"skill": "superpowers:unknown-standard-skill"},
                [claude_tool_result("standard-tdd")],
            ),
        )
        for label, tool_input, result_events in claude_cases:
            with self.subTest(backend="claude", label=label):
                events = [
                    claude_init(),
                    claude_event("Mode: standard — bounded CLI behavior and coverage."),
                    claude_tool_event(
                        "Skill", tool_input, tool_id="standard-tdd"
                    ),
                    *result_events,
                    *claude_read_lifecycle(self.project, "src/cli.js", "inspection"),
                    claude_event(outline),
                    claude_tool_event(
                        "Write",
                        {"file_path": str(self.project / "src/cli.js"), "content": "code"},
                        tool_id="mutation",
                    ),
                    claude_event("Tests passed."),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "standard", events)
                self.assertNotEqual(result.returncode, 0)

        valid_items = [{"text": "Inspect the CLI", "completed": False}]
        malformed_codex_cases = (
            (
                "extra todo key",
                [
                    {
                        "type": "item.started",
                        "item": {
                            "id": "tasks",
                            "type": "todo_list",
                            "items": valid_items,
                            "status": "in_progress",
                        },
                    },
                    codex_todo_event("item.completed", "tasks", valid_items),
                ],
            ),
            (
                "items is not a list",
                [
                    {
                        "type": "item.started",
                        "item": {
                            "id": "tasks",
                            "type": "todo_list",
                            "items": "malformed",
                        },
                    },
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "tasks",
                            "type": "todo_list",
                            "items": "malformed",
                        },
                    },
                ],
            ),
            (
                "todo entry has extra key",
                [
                    codex_todo_event(
                        "item.started",
                        "tasks",
                        [
                            {
                                "text": "Inspect the CLI",
                                "completed": False,
                                "priority": "high",
                            }
                        ],
                    ),
                    codex_todo_event("item.completed", "tasks", valid_items),
                ],
            ),
            (
                "todo entry completed is not boolean",
                [
                    codex_todo_event(
                        "item.started",
                        "tasks",
                        [{"text": "Inspect the CLI", "completed": 0}],
                    ),
                    codex_todo_event("item.completed", "tasks", valid_items),
                ],
            ),
            (
                "unstable todo id",
                [
                    codex_todo_event("item.started", "tasks", valid_items),
                    codex_todo_event("item.updated", "renamed-tasks", valid_items),
                    codex_todo_event("item.completed", "tasks", valid_items),
                ],
            ),
            (
                "unstable todo type",
                [
                    codex_todo_event("item.started", "tasks", valid_items),
                    {
                        "type": "item.updated",
                        "item": {
                            "id": "tasks",
                            "type": "task_list",
                            "items": valid_items,
                        },
                    },
                    codex_todo_event("item.completed", "tasks", valid_items),
                ],
            ),
            (
                "out-of-order todo update",
                [
                    codex_todo_event("item.updated", "tasks", valid_items),
                    codex_todo_event("item.started", "tasks", valid_items),
                    codex_todo_event("item.completed", "tasks", valid_items),
                ],
            ),
        )
        for label, todo_events in malformed_codex_cases:
            with self.subTest(backend="codex", label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded CLI behavior and coverage.",
                        item_id="mode",
                    ),
                    *todo_events,
                    *codex_command_lifecycle(
                        "cat src/cli.js items.json", "inspection"
                    ),
                    codex_event(outline, item_id="outline"),
                    *codex_command_lifecycle("printf implementation", "mutation"),
                    codex_event("Tests passed.", item_id="result"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)

    def test_lean_accepts_an_evidence_heading_as_verification_reporting(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — localized typo fix.\n"
                "Evidence:\n- grep found no typo\n- git diff contains only README.md"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "lean", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_prompt_echo_without_assistant_declaration(self) -> None:
        events = [
            {"type": "user", "message": {"role": "user", "content": "Mode: lean"}},
            {"type": "thread.started", "thread_id": "thread"},
            codex_event("Finished the task and verified it."),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "lean", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assistant prose before mode declaration", result.stderr)

    def test_preserves_assistant_text_when_validation_fails(self) -> None:
        log = self.write_jsonl(
            "missing-mode.jsonl",
            [
                {"type": "thread.started", "thread_id": "thread"},
                codex_event("Finished and verified without a declaration."),
                {"type": "turn.completed", "usage": {}},
            ],
        )
        assistant = self.root / "assistant.txt"
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "codex",
                "test-model",
                "lean",
                str(log),
                str(assistant),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(assistant.is_file())
        self.assertEqual(
            assistant.read_text(),
            "Finished and verified without a declaration.\n",
        )

    def test_rejects_duplicate_assistant_declarations(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event("Mode: lean — first.", item_id="first"),
            codex_event("Mode: lean — repeated.", item_id="second"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "lean", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("found 2", result.stderr)

    def test_rejects_wrong_mode_even_when_count_is_one(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event("Mode: strict — wrong for this fixture."),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "lean", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected Mode: lean", result.stderr)

    def test_rejects_malformed_jsonl(self) -> None:
        log = self.root / "malformed.jsonl"
        log.write_text('{"type":"thread.started"}\nnot json\n')
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "codex", "test-model", "lean", str(log)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid JSON on line 2", result.stderr)

    def test_rejects_incomplete_backend_runs(self) -> None:
        claude = self.run_validator(
            "claude",
            "lean",
            [
                {"type": "system", "subtype": "init", "model": "test-model"},
                claude_event("Mode: lean — incomplete."),
            ],
        )
        codex = self.run_validator(
            "codex",
            "lean",
            [
                {"type": "thread.started", "thread_id": "thread"},
                codex_event("Mode: lean — incomplete."),
            ],
        )
        self.assertNotEqual(claude.returncode, 0)
        self.assertIn("successful result event", claude.stderr)
        self.assertNotEqual(codex.returncode, 0)
        self.assertIn("turn.completed", codex.stderr)

    def test_rejects_claude_model_alias_or_fallback(self) -> None:
        events = [
            {"type": "system", "subtype": "init", "model": "different-model"},
            claude_event("Mode: lean — typo."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "lean", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected model test-model", result.stderr)

    def test_escalation_accepts_standard_inspection_promotion_then_pause(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_claude_accepts_successful_project_read_result(self) -> None:
        events = [
            claude_init(),
            claude_event(
                "Mode: standard — bounded rename pending repository inspection."
            ),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?"
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_claude_allows_project_glob_and_grep_before_exact_reads(self) -> None:
        for name, tool_input in (
            ("Glob", {"path": str(self.project), "pattern": "src/*.js"}),
            ("Grep", {"path": str(self.project), "pattern": "amount"}),
        ):
            with self.subTest(name=name):
                events = [
                    claude_init(),
                    claude_event(
                        "Mode: standard — bounded rename pending repository inspection."
                    ),
                    claude_tool_event(name, tool_input, tool_id="inspect"),
                    claude_tool_result("inspect"),
                    *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
                    *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
                    claude_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias during migration?"
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "escalation", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_claude_requires_correlated_successful_tool_result(self) -> None:
        read = claude_tool_event(
            "Read",
            {"file_path": str(self.project / "src/schema.js")},
            tool_id="inspect",
        )
        invalid_results = (
            ("missing", [], "tool result"),
            ("mismatched", [claude_tool_result("different")], "tool result"),
            (
                "error",
                [claude_tool_result("inspect", is_error=True)],
                "schema.js and src/billing.js",
            ),
        )
        for label, result_events, expected_error in invalid_results:
            with self.subTest(label=label):
                events = [
                    claude_init(),
                    claude_event(
                        "Mode: standard — bounded rename pending repository inspection."
                    ),
                    *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
                    read,
                    *result_events,
                    claude_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias during migration?"
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_escalation_claude_failed_optional_read_is_neutral(self) -> None:
        (self.project / "src/billing.js").write_text(
            "export const response = payment => ({ amount: payment.amount });\n"
        )
        declaration = claude_event(
            "Mode: standard — bounded rename pending repository inspection."
        )
        schema = [
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/schema.js")},
                tool_id="schema",
            ),
            claude_tool_result("schema"),
        ]
        billing = [
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/billing.js")},
                tool_id="billing",
            ),
            claude_tool_result("billing"),
        ]
        missing = [
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/optional.js")},
                tool_id="optional",
            ),
            claude_tool_result("optional", is_error=True, content="not found"),
        ]
        promotion = claude_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?"
        )
        for label, inspections in (
            ("successful reads then failed optional probe", [*schema, *billing, *missing]),
            ("failed optional probe then successful reads", [*missing, *schema, *billing]),
        ):
            with self.subTest(label=label):
                events = [
                    claude_init(),
                    declaration,
                    *inspections,
                    promotion,
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "escalation", events)
                self.assertEqual(result.returncode, 0, result.stderr)

        no_success = [
            claude_init(),
            declaration,
            *missing,
            promotion,
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", no_success)
        self.assertNotEqual(result.returncode, 0)

    def test_escalation_requires_successful_schema_and_billing_reads(self) -> None:
        (self.project / "src/billing.js").write_text(
            "export const response = payment => ({ amount: payment.amount });\n"
        )
        promotion_text = (
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?"
        )

        def claude_read(path: str, tool_id: str, *, failed: bool = False) -> list[dict]:
            return [
                claude_tool_event(
                    "Read",
                    {"file_path": str(self.project / path)},
                    tool_id=tool_id,
                ),
                claude_tool_result(tool_id, is_error=failed),
            ]

        def codex_read(
            path: str, tool_id: str, *, wrapped: bool, failed: bool = False
        ) -> list[dict]:
            command = f"sed -n '1,20p' {path}"
            if wrapped:
                command = f'/bin/zsh -lc "{command}"'
            return codex_command_lifecycle(
                command,
                tool_id,
                exit_code=1 if failed else 0,
            )

        claude_cases = (
            ("schema only", claude_read("src/schema.js", "schema"), False),
            ("billing only", claude_read("src/billing.js", "billing"), False),
            (
                "failed billing",
                [
                    *claude_read("src/schema.js", "schema"),
                    *claude_read("src/billing.js", "billing", failed=True),
                ],
                False,
            ),
            (
                "both success",
                [
                    *claude_read("src/schema.js", "schema"),
                    *claude_read("src/billing.js", "billing"),
                ],
                True,
            ),
        )
        for label, reads, accepted in claude_cases:
            with self.subTest(backend="claude", case=label):
                events = [
                    claude_init(),
                    claude_event(
                        "Mode: standard — bounded rename pending repository inspection."
                    ),
                    *reads,
                    claude_event(promotion_text),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "escalation", events)
                if accepted:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("schema.js and src/billing.js", result.stderr)

        for wrapped in (False, True):
            codex_cases = (
                (
                    "schema only",
                    codex_read("src/schema.js", "schema", wrapped=wrapped),
                    False,
                ),
                (
                    "billing only",
                    codex_read("src/billing.js", "billing", wrapped=wrapped),
                    False,
                ),
                (
                    "failed billing",
                    [
                        *codex_read("src/schema.js", "schema", wrapped=wrapped),
                        *codex_read(
                            "src/billing.js", "billing", wrapped=wrapped, failed=True
                        ),
                    ],
                    False,
                ),
                (
                    "both success",
                    [
                        *codex_read("src/schema.js", "schema", wrapped=wrapped),
                        *codex_read("src/billing.js", "billing", wrapped=wrapped),
                    ],
                    True,
                ),
            )
            for label, reads, accepted in codex_cases:
                with self.subTest(backend="codex", wrapped=wrapped, case=label):
                    events = [
                        {"type": "thread.started", "thread_id": "thread"},
                        codex_event(
                            "Mode: standard — bounded rename pending repository inspection.",
                            item_id="declaration",
                        ),
                        *reads,
                        codex_event(promotion_text, item_id="promotion"),
                        {"type": "turn.completed", "usage": {}},
                    ]
                    result = self.run_validator("codex", "escalation", events)
                    if accepted:
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("schema.js and src/billing.js", result.stderr)

    def test_escalation_claude_rejects_assistant_authored_tool_result(self) -> None:
        assistant_result = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "inspect",
                        "is_error": False,
                        "content": "claimed success",
                    }
                ],
            },
        }
        events = [
            claude_init(),
            claude_event(
                "Mode: standard — bounded rename pending repository inspection."
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/schema.js")},
                tool_id="inspect",
            ),
            assistant_result,
            claude_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?"
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("user-role tool result", result.stderr)

    def test_escalation_claude_tool_result_is_error_has_closed_json_type(self) -> None:
        absent = claude_tool_result("inspect")
        del absent["message"]["content"][0]["is_error"]
        valid_results = (
            ("absent", absent),
            ("false", claude_tool_result("inspect", is_error=False)),
        )
        invalid_results = (
            (
                "true",
                claude_tool_result("inspect", is_error=True),
                "schema.js and src/billing.js",
            ),
            ("string", claude_tool_result("inspect", is_error="false"), "is_error"),
            ("zero", claude_tool_result("inspect", is_error=0), "is_error"),
            ("one", claude_tool_result("inspect", is_error=1), "is_error"),
            ("list", claude_tool_result("inspect", is_error=[]), "is_error"),
            ("object", claude_tool_result("inspect", is_error={}), "is_error"),
            ("null", claude_tool_result("inspect", is_error=None), "is_error"),
        )

        def events_for(result_event: dict) -> list[dict]:
            return [
                claude_init(),
                claude_event(
                    "Mode: standard — bounded rename pending repository inspection."
                ),
                *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
                claude_tool_event(
                    "Read",
                    {"file_path": str(self.project / "src/schema.js")},
                    tool_id="inspect",
                ),
                result_event,
                claude_event(
                    f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                    "Should we retain the compatibility alias during migration?"
                ),
                {"type": "result", "subtype": "success", "result": "done"},
            ]

        for label, result_event in valid_results:
            with self.subTest(label=label):
                result = self.run_validator(
                    "claude", "escalation", events_for(result_event)
                )
                self.assertEqual(result.returncode, 0, result.stderr)
        for label, result_event, expected_error in invalid_results:
            with self.subTest(label=label):
                result = self.run_validator(
                    "claude", "escalation", events_for(result_event)
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_escalation_claude_rejects_invalid_project_inspection_inputs(self) -> None:
        invalid_tools = (
            ("Read", {"file_path": ""}),
            ("Read", {"file_path": str(self.root / "outside.js")}),
            ("Glob", {"path": str(self.project), "pattern": ""}),
            ("Glob", {"path": str(self.root), "pattern": "*.js"}),
            ("Grep", {"path": str(self.project), "pattern": ""}),
            ("Grep", {"path": str(self.root), "pattern": "amount"}),
        )
        for name, tool_input in invalid_tools:
            with self.subTest(name=name, tool_input=tool_input):
                events = [
                    claude_init(),
                    claude_event(
                        "Mode: standard — bounded rename pending repository inspection."
                    ),
                    claude_tool_event(name, tool_input, tool_id="inspect"),
                    claude_tool_result("inspect"),
                    claude_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias during migration?"
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid project inspection", result.stderr)

    def test_escalation_claude_rejects_unknown_tools_before_and_after_promotion(self) -> None:
        declaration = claude_event(
            "Mode: standard — bounded rename pending repository inspection."
        )
        inspection = [
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
        ]
        promotion = claude_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?"
        )
        unknowns = ("Task", "mcp__example__read")
        for name in unknowns:
            for position in ("before", "after"):
                with self.subTest(name=name, position=position):
                    unknown = claude_tool_event(name, {}, tool_id="unknown")
                    body = (
                        [declaration, unknown, *inspection, promotion]
                        if position == "before"
                        else [declaration, *inspection, promotion, unknown]
                    )
                    events = [
                        claude_init(),
                        *body,
                        {"type": "result", "subtype": "success", "result": "done"},
                    ]
                    result = self.run_validator("claude", "escalation", events)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("unrecognized escalation action", result.stderr)

    def test_escalation_codex_requires_successful_completed_inspection(self) -> None:
        symlink = self.project / "src/schema-link.js"
        symlink.symlink_to(self.project / "src/schema.js")
        for label, lifecycle, expected_error in (
            (
                "failed",
                codex_command_lifecycle(
                    "cat src/schema.js src/billing.js", "inspection", exit_code=1
                ),
                "schema.js and src/billing.js",
            ),
            (
                "missing exit code",
                codex_command_lifecycle(
                    "cat src/schema.js src/billing.js", "inspection", exit_code=None
                ),
                "completed inspection exit code",
            ),
            (
                "cat missing file exits one",
                codex_command_lifecycle(
                    "cat src/missing-schema.js", "inspection", exit_code=1
                ),
                "schema.js and src/billing.js",
            ),
            (
                "claimed exit zero for missing file",
                codex_command_lifecycle(
                    "cat src/claimed-present.js", "inspection", exit_code=0
                ),
                "claimed success",
            ),
            (
                "symlink is not a regular project file operand",
                codex_command_lifecycle(
                    "cat src/schema-link.js", "inspection", exit_code=0
                ),
                "mutation before strict promotion/approval pause",
            ),
        ):
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *lifecycle,
                    codex_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_escalation_codex_failed_optional_read_is_neutral(self) -> None:
        (self.project / "src/billing.js").write_text(
            "export const response = payment => ({ amount: payment.amount });\n"
        )
        declaration = codex_event(
            "Mode: standard — bounded rename pending repository inspection.",
            item_id="declaration",
        )
        schema = codex_command_lifecycle(
            "/bin/zsh -lc \"sed -n '1,20p' src/schema.js\"", "schema"
        )
        billing = codex_command_lifecycle(
            "/bin/zsh -lc \"sed -n '1,20p' src/billing.js\"", "billing"
        )
        missing = codex_command_lifecycle(
            "/bin/zsh -lc \"sed -n '1,20p' src/optional.js\"",
            "optional",
            exit_code=1,
        )
        promotion = codex_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?",
            item_id="promotion",
        )
        for label, inspections in (
            ("successful reads then failed optional probe", [*schema, *billing, *missing]),
            ("failed optional probe then successful reads", [*missing, *schema, *billing]),
        ):
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    declaration,
                    *inspections,
                    promotion,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertEqual(result.returncode, 0, result.stderr)

        no_success = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration,
            *missing,
            promotion,
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", no_success)
        self.assertNotEqual(result.returncode, 0)

        failed_mutation = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration,
            *codex_command_lifecycle(
                "python3 -c 'open(\"src/schema.js\", \"w\").write(\"x\")'",
                "mutation",
                exit_code=1,
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", failed_mutation)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mutation before strict promotion/approval pause", result.stderr)

    def test_escalation_codex_uses_closed_cat_and_sed_inspection_grammar(self) -> None:
        invalid_commands = (
            "./cat src/schema.js",
            "/bin/cat src/schema.js",
            "sed -n 1p src/schema.js -i.bak",
            "rg --pre amount src/schema.js",
        )
        for command in invalid_commands:
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(command, "inspection", exit_code=0),
                    codex_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias "
                        "during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mutation before strict promotion/approval pause", result.stderr)

    def test_escalation_codex_accepts_closed_sed_print_inspection(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("sed -n '1,20p' src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_codex_accepts_platform_wrapped_sed_inspections(self) -> None:
        (self.project / "src/billing.js").write_text(
            "export const response = payment => ({ amount: payment.amount });\n"
        )
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,20p' src/schema.js\"",
                "schema-inspection",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,20p' src/billing.js\"",
                "billing-inspection",
            ),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_codex_allows_glob_discovery_before_literal_reads(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,240p' src/*\"",
                "glob-discovery",
            ),
            *codex_command_lifecycle("cat src/schema.js", "schema"),
            *codex_command_lifecycle("cat src/billing.js", "billing"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_safe_rg_discovery_between_literal_reads(self) -> None:
        # Exact discovery command from final-0e112a1 Codex escalation.
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — this is a bounded schema-and-consumer rename "
                "whose compatibility surface needs repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,240p' src/schema.js\"", "schema"
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"rg -n \\\"amount|payment\\\" . --glob "
                "'!node_modules/**' --glob '!.git/**'\"",
                "discovery",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,240p' src/billing.js\"", "billing"
            ),
            codex_event(
                f"Promoting to strict — {REAL_CODEX_PROMOTION_REASON}\n"
                "Inspection shows this rename changes a public billing API response "
                "from `amount` to `amountCents`, making it a breaking payments-facing "
                "change. Should I proceed in strict mode and update the schema, "
                "consumer, and tests?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rg_discovery_never_satisfies_literal_escalation_proof(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("rg --files", "discovery"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema.js and src/billing.js", result.stderr)

    def test_rg_discovery_grammar_rejects_unsafe_or_unknown_composition(self) -> None:
        outline = (
            "Plan: modify src/cli.js to add the item summary command; cover "
            "test/summary.test.js; run npm test and verify JSON count/total."
        )
        unsafe = (
            "rg --files > files.txt",
            "rg --files | tee files.txt",
            "rg --files && sed -n '1,20p' src/cli.js",
            "rg --files || true",
            "rg --files $(touch owned)",
            "rg --files `touch owned`",
            "rg --files\nprintf owned",
            "rg --files | unknown-filter",
            "rg --files --sort path",
            "rg -n amount . --replace changed",
            "rg -n --pre 'touch owned' .",
            "rg -n amount . --pre 'touch owned'",
            "rg -n --hostname-bin 'touch owned' amount .",
            "rg --files ../outside",
            "rg --files /tmp",
            "rg -n $EVIL .",
            "rg -n ${EVIL} .",
            "rg -n foo$EVIL .",
            "rg -n {--pre=touch,amount} .",
            "rg --files $EVIL",
            "rg --files ~",
            "rg --files {.,..}",
            "rg --files {.,/tmp}",
            "rg --files *",
            "rg --files -g *",
            "rg -n amount+payment .",
            "rg -n amount.payment .",
            "rg -n amount^payment .",
            r"rg -n amount\*payment .",
            r"rg --files -g \*.js",
            "rg --files | sed -n '0,10p'",
            "rg --files | sed -n '-1,10p'",
            "rg --files | sed -n 'one,10p'",
            "rg --files | sed -n '1,10'",
            "rg --files | sed -n '$p'",
        )
        for index, command in enumerate(unsafe):
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded CLI behavior and coverage.",
                        item_id="mode",
                    ),
                    *codex_command_lifecycle(command, f"unsafe-{index}"),
                    codex_event(outline, item_id="outline"),
                    codex_event(
                        "src/cli.js",
                        item_type="file_change",
                        event_type="item.started",
                        item_id="mutation",
                    ),
                    codex_event(
                        "src/cli.js", item_type="file_change", item_id="mutation"
                    ),
                    codex_event("Verification: npm test passes.", item_id="result"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)

    def test_escalation_discovery_does_not_satisfy_literal_read_proof(self) -> None:
        promotion = (
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?"
        )
        claude_discovery = [
            claude_init(),
            claude_event(
                "Mode: standard — bounded rename pending repository inspection."
            ),
            claude_tool_event(
                "Glob",
                {"path": str(self.project), "pattern": "src/*.js"},
                tool_id="discovery",
            ),
            claude_tool_result(
                "discovery", content="src/schema.js\nsrc/billing.js"
            ),
            claude_event(promotion),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        codex_glob_only = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,240p' src/*\"",
                "glob-discovery",
            ),
            codex_event(promotion, item_id="promotion"),
            {"type": "turn.completed", "usage": {}},
        ]
        codex_mixed_glob_and_literals = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "cat src/* src/schema.js src/billing.js",
                "mixed-discovery",
            ),
            codex_event(promotion, item_id="promotion"),
            {"type": "turn.completed", "usage": {}},
        ]
        for label, backend, events in (
            ("Claude Glob", "claude", claude_discovery),
            ("Codex glob", "codex", codex_glob_only),
            ("Codex mixed glob and literals", "codex", codex_mixed_glob_and_literals),
        ):
            with self.subTest(label=label):
                result = self.run_validator(backend, "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("schema.js and src/billing.js", result.stderr)

    def test_escalation_codex_project_glob_is_closed_and_no_match_is_neutral(
        self,
    ) -> None:
        declaration = codex_event(
            "Mode: standard — bounded rename pending repository inspection.",
            item_id="declaration",
        )
        promotion = codex_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?",
            item_id="promotion",
        )
        missing = codex_command_lifecycle(
            "/bin/zsh -lc \"sed -n '1,20p' src/no-match-*\"",
            "missing-glob",
            exit_code=1,
        )
        no_match_only = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration,
            *missing,
            promotion,
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", no_match_only)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema.js and src/billing.js", result.stderr)

        missing_then_exact_reads = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration,
            *missing,
            *codex_command_lifecycle("cat src/schema.js", "schema"),
            *codex_command_lifecycle("cat src/billing.js", "billing"),
            promotion,
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "escalation", missing_then_exact_reads
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        (self.project / "src/schema-link.js").symlink_to(
            self.project / "src/schema.js"
        )
        (self.project / "src/nested").mkdir()
        unsafe_patterns = (
            "/bin/zsh -lc \"sed -n '1,20p' src/../*\"",
            "/bin/zsh -lc \"sed -n '1,20p' /tmp/*\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/*-link.js\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/nest*\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/**\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/{schema,billing}.js\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/?.js\"",
        )
        for index, command in enumerate(unsafe_patterns):
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    declaration,
                    *codex_command_lifecycle(command, f"unsafe-glob-{index}"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "mutation before strict promotion/approval pause", result.stderr
                )

    def test_escalation_codex_rejects_escaped_operand_metacharacters(self) -> None:
        for name in ("*", "?", "["):
            (self.project / "src" / name).write_text("literal metachar file\n")
        declaration = codex_event(
            "Mode: standard — bounded rename pending repository inspection.",
            item_id="declaration",
        )
        promotion = codex_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?",
            item_id="promotion",
        )
        commands = (
            "/bin/zsh -lc \"sed -n '1,20p' src/\\*\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/\\?\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/\\[\"",
        )
        for index, command in enumerate(commands):
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    declaration,
                    *codex_command_lifecycle(command, f"escaped-{index}"),
                    promotion,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "mutation before strict promotion/approval pause", result.stderr
                )

    def test_escalation_codex_no_match_does_not_hide_invalid_later_operand(
        self,
    ) -> None:
        (self.project / "src/nested").mkdir()
        (self.project / "src/schema-link.js").symlink_to(
            self.project / "src/schema.js"
        )
        declaration = codex_event(
            "Mode: standard — bounded rename pending repository inspection.",
            item_id="declaration",
        )
        promotion = codex_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?",
            item_id="promotion",
        )

        safe_no_match = codex_command_lifecycle(
            "/bin/zsh -lc \"sed -n '1,20p' src/no-match-* src/optional.js\"",
            "safe-no-match",
            exit_code=1,
        )
        safe_events = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration,
            *safe_no_match,
            *codex_command_lifecycle("cat src/schema.js", "schema"),
            *codex_command_lifecycle("cat src/billing.js", "billing"),
            promotion,
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", safe_events)
        self.assertEqual(result.returncode, 0, result.stderr)

        invalid_later_operands = (
            str(self.project / "src/schema.js"),
            "src/nested",
            "src/schema-link.js",
            "src/../src/schema.js",
            "src/{schema,billing}.js",
        )
        for index, operand in enumerate(invalid_later_operands):
            with self.subTest(operand=operand):
                command = (
                    "/bin/zsh -lc \"sed -n '1,20p' "
                    f"src/no-match-* {operand}\""
                )
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    declaration,
                    *codex_command_lifecycle(
                        command,
                        f"invalid-after-no-match-{index}",
                        exit_code=1,
                    ),
                    *codex_command_lifecycle("cat src/schema.js", "schema"),
                    *codex_command_lifecycle("cat src/billing.js", "billing"),
                    promotion,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "mutation before strict promotion/approval pause", result.stderr
                )

    def test_escalation_codex_rejects_unsafe_wrapped_project_commands(self) -> None:
        (self.project / "src/billing.js").write_text("export const billing = {};\n")
        commands = (
            "/bin/zsh -lc \"sed -n '1,20p' src/schema.js && "
            "sed -n '1,20p' src/billing.js\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/schema.js | cat\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/schema.js > /tmp/schema\"",
            "/bin/zsh -lc \"sed -n '1,20p' $(printf src/schema.js)\"",
            "/bin/zsh -lc \"sed -n '1,20p' src/schema.js -i.bak\"",
            "/bin/zsh -lc \"python3 -c 'open(\\\"src/schema.js\\\", "
            "\\\"w\\\").write(\\\"changed\\\")'\"",
        )
        for command in commands:
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(command, "unsafe"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "mutation before strict promotion/approval pause", result.stderr
                )

    def test_escalation_codex_rejects_find_delete_and_unknown_items(self) -> None:
        unsafe = codex_command_lifecycle(
            "find src -delete", "unsafe", exit_code=0
        )
        unknown = [
            codex_event(
                "opaque",
                item_type="mcp_tool_call",
                event_type="item.started",
                item_id="unknown",
            ),
            codex_event(
                "opaque", item_type="mcp_tool_call", item_id="unknown"
            ),
        ]
        promotion = [
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
        ]
        for label, action, expected_error in (
            ("find delete", unsafe, "mutation before strict promotion/approval pause"),
            ("unknown MCP item", unknown, "unrecognized escalation action"),
            (
                "unknown MCP item after promotion",
                [*promotion, *unknown],
                "unrecognized escalation action",
            ),
        ):
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *action,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_escalation_rejects_negated_or_harmless_promotion_reasons(self) -> None:
        reasons = (
            "inspection found no public API or payment compatibility risk; this change is harmless",
            "inspection found the change has no payment or public API breaking compatibility risk",
            "inspection found the change works without any public API compatibility risk",
            "inspection found this is not a breaking compatibility change for the public API",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {reason}.\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_rejects_unrelated_words_as_promotion_evidence(self) -> None:
        reasons = (
            "inspection found docs mention public API breaking compatibility risk in payment billing",
            "inspection found code contains the token public API payment compatibility risk",
            "inspection found schema docs list payment and public API vocabulary",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {reason}.\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_promotion_rejects_explicit_disclaimers(self) -> None:
        invalid_reasons = (
            "documentation quotes: " + CANONICAL_PROMOTION_REASON,
            "the documentation says " + CANONICAL_PROMOTION_REASON,
            "inspection found src/schema.js contains a quotation that the amount "
            "field consumed by src/billing.js is part of the public payment API; "
            "renaming it would break compatibility.",
            CANONICAL_PROMOTION_REASON + " This is only an unrelated docs note.",
            CANONICAL_PROMOTION_REASON.replace(
                "would break compatibility", "would not break compatibility"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API", "public payment API without a response surface"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "would break compatibility",
                "would break compatibility as a harmless example",
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API", "unrelated public payment API response surface"
            ),
        )
        for reason in invalid_reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_promotion_rejects_opposing_and_quoted_claims(self) -> None:
        claimed_relation = CANONICAL_PROMOTION_REASON.removesuffix(".")
        relation_after_inspection = claimed_relation.removeprefix("inspection found ")
        evidence, consequence = relation_after_inspection.split("; ", maxsplit=1)
        invalid_reasons = (
            CANONICAL_PROMOTION_REASON.replace(
                "defines the amount field", "doesn't define the amount field"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "defines the amount field", "never defines the amount field"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "consumed by", "never consumed by"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "amount field consumed by", "amount field isn't consumed by"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "consumed by", "cannot be consumed by"
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "would break compatibility.", "would never break compatibility."
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "would break compatibility.",
                "would never change a compatibility contract.",
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "would break compatibility.", "would fail to break compatibility."
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "would break compatibility.",
                "would break compatibility, but actually preserve compatibility.",
            ),
            claimed_relation + ", though that claim is incorrect.",
            f"inspection found the note '{relation_after_inspection}'.",
            f"inspection found the note ‘{relation_after_inspection}’.",
            f"inspection found the note «{relation_after_inspection}».",
            f"inspection found the note '{evidence}'; {consequence}.",
        )
        for reason in invalid_reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(
                        "cat src/schema.js src/billing.js", "inspection"
                    ),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_promotion_accepts_separate_benign_quoted_modifiers(
        self,
    ) -> None:
        reason = CANONICAL_PROMOTION_REASON.replace(
            "inspection found", "inspection found 'direct evidence'"
        ).replace(
            "break compatibility.", "break compatibility 'confirmed'."
        )
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "cat src/schema.js src/billing.js", "inspection"
            ),
            codex_event(
                f"Promoting to strict — {reason}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_promotion_rejects_question_and_malformed_transition(
        self,
    ) -> None:
        invalid_reasons = (
            CANONICAL_PROMOTION_REASON.removesuffix(".") + "?",
        )
        for reason in invalid_reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(
                        "cat src/schema.js src/billing.js", "inspection"
                    ),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

        ascii_separator_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict - {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", ascii_separator_events)
        self.assertNotEqual(result.returncode, 0)

    def test_escalation_promotion_accepts_noncontradictory_modifiers(self) -> None:
        reasons = (
            CANONICAL_PROMOTION_REASON.removesuffix(".") + " 2.",
            CANONICAL_PROMOTION_REASON.removesuffix(".") + " 補充.",
            CANONICAL_PROMOTION_REASON.removesuffix(".") + " 🔥.",
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API response surface",
                "public payment 2 API response surface",
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API response surface",
                "public payment 補充 API response surface",
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API response surface",
                "public payment / API response surface",
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API response surface",
                "public payment banana API response surface",
            ),
            CANONICAL_PROMOTION_REASON.replace("API response surface;", "API response surface;;"),
            CANONICAL_PROMOTION_REASON.replace(
                "break compatibility.", "break compatibility,,."
            ),
            CANONICAL_PROMOTION_REASON + ".",
            (
                "inspection found src/schema.js defines amount consumed by "
                "src/billing.js's unexpectedAlias as part of the public payment API "
                "response surface; renaming amount to amountCents would break "
                "compatibility."
            ),
            CANONICAL_PROMOTION_REASON.replace(
                "public payment API response surface",
                "public payment API response surface 2026 補充 🔥 ---- {} /_ :::",
            ),
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(
                        "cat src/schema.js src/billing.js", "inspection"
                    ),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_promotion_rejects_invalid_inline_code_formatting(
        self,
    ) -> None:
        invalid_reasons = (
            CANONICAL_PROMOTION_REASON.removesuffix(".") + " ---- {} /_ ::: ``.",
            CANONICAL_PROMOTION_REASON.replace("amount field", "`amount field"),
        )
        for reason in invalid_reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(
                        "cat src/schema.js src/billing.js", "inspection"
                    ),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_accepts_structured_real_promotion_relations(self) -> None:
        reasons = (
            REAL_CLAUDE_PROMOTION_REASON,
            REAL_CODEX_PROMOTION_REASON,
            "inspection found src/schema.js defines `amount` consumed by "
            "src/billing.js (`publicPaymentResponse` returns "
            "`{amount : payment . amount}`) as part of the public billing API "
            "payment surface; renaming amount to amountCents would break the "
            "public billing API response shape for external consumers.",
            "inspection found src/schema.js defines the amount field and "
            "src/billing.js uses it in the public payment API response surface; "
            "renaming amount to amountCents would cause a breaking public API "
            "compatibility change.",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_exact_claude_possessive_consumer_promotion(
        self,
    ) -> None:
        events = [
            claude_init(),
            claude_event(
                "Mode: standard — bounded rename pending repository inspection."
            ),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(
                REAL_CLAUDE_POSSESSIVE_PROMOTION
                + "\nShould we retain the compatibility alias during migration?"
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_verbose_claude_output(self) -> None:
        events = [
            claude_init(),
            claude_event(LATEST_CLAUDE_INITIAL_OUTPUT),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/api.js")},
                tool_id="optional-api",
            ),
            claude_tool_result(
                "optional-api", is_error=True, content="File does not exist."
            ),
            claude_event(LATEST_CLAUDE_FINAL_OUTPUT),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_multimessage_codex_output(self) -> None:
        _preamble, declaration, promotion, explanation_and_pause = LATEST_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(declaration, item_id="declaration"),
            *codex_command_lifecycle("sed -n '1,200p' src/schema.js", "schema"),
            *codex_command_lifecycle(
                "sed -n '1,200p' src/api.js", "optional-api", exit_code=2
            ),
            *codex_command_lifecycle("sed -n '1,200p' src/billing.js", "billing"),
            codex_event(promotion, item_id="promotion"),
            codex_event(explanation_and_pause, item_id="pause"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_19a_claude_output(self) -> None:
        events = [
            claude_init(),
            claude_event(LATEST_19A_CLAUDE_INITIAL_OUTPUT),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(LATEST_19A_CLAUDE_FINAL_OUTPUT),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_19a_codex_output(self) -> None:
        _preamble, declaration, promotion_and_pause = LATEST_19A_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(declaration, item_id="declaration"),
            *codex_command_lifecycle("sed -n '1,240p' src/schema.js", "schema"),
            *codex_command_lifecycle(
                "sed -n '1,240p' src/api.js", "optional-api", exit_code=1
            ),
            *codex_command_lifecycle("sed -n '1,240p' src/billing.js", "billing"),
            codex_event(promotion_and_pause, item_id="promotion"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_f9a_claude_output(self) -> None:
        events = [
            claude_init(),
            claude_event(LATEST_F9A_CLAUDE_INITIAL_OUTPUT),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            claude_event(LATEST_F9A_CLAUDE_MIDDLE_OUTPUT),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(LATEST_F9A_CLAUDE_FINAL_OUTPUT),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_f9a_codex_output(self) -> None:
        _preamble, declaration, promotion, pause = LATEST_F9A_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Loading workflow-selection sources before task analysis.",
                item_id="preamble",
            ),
            codex_event(declaration, item_id="declaration"),
            *codex_command_lifecycle("sed -n '1,240p' src/schema.js", "schema"),
            *codex_command_lifecycle("sed -n '1,240p' src/billing.js", "billing"),
            codex_event(promotion, item_id="promotion"),
            codex_event(pause, item_id="pause"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_f1b_claude_output(self) -> None:
        events = [
            claude_init(),
            claude_event(LATEST_F1B_CLAUDE_INITIAL_OUTPUT),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(LATEST_F1B_CLAUDE_FINAL_OUTPUT),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_f1b_codex_output(self) -> None:
        _preamble, declaration, promotion_and_pause = LATEST_F1B_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(declaration, item_id="declaration"),
            *codex_command_lifecycle("sed -n '1,240p' src/schema.js", "schema"),
            *codex_command_lifecycle(
                "sed -n '1,240p' src/api.js", "optional-api", exit_code=1
            ),
            *codex_command_lifecycle("sed -n '1,240p' src/billing.js", "billing"),
            codex_event(promotion_and_pause, item_id="promotion"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_e52_claude_output(self) -> None:
        events = [
            claude_init(),
            claude_event(LATEST_E52_CLAUDE_INITIAL_OUTPUT),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            claude_event(LATEST_E52_CLAUDE_MIDDLE_OUTPUT),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(LATEST_E52_CLAUDE_FINAL_OUTPUT),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_be5_claude_output(self) -> None:
        events = [
            claude_init(),
            claude_event(LATEST_BE5_CLAUDE_INITIAL_OUTPUT),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            claude_event(LATEST_BE5_CLAUDE_FINAL_OUTPUT),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_latest_be5_codex_output(self) -> None:
        _preamble, declaration, promotion, pause = LATEST_BE5_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(declaration, item_id="declaration"),
            *codex_command_lifecycle("sed -n '1,240p' src/schema.js", "schema"),
            *codex_command_lifecycle("sed -n '1,240p' src/billing.js", "billing"),
            codex_event(promotion, item_id="promotion"),
            codex_event(pause, item_id="pause"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_structured_promotion_rejects_missing_or_safe_relations(
        self,
    ) -> None:
        reasons = (
            "inspection found amount consumed by src/billing.js in a public billing "
            "API response; renaming it would create a breaking API change.",
            "inspection found src/schema.js defines a field consumed by src/billing.js "
            "in a public billing API response; renaming it would create a breaking "
            "API change.",
            "inspection found src/schema.js defines amount in a public billing API "
            "response; renaming it would create a breaking API change.",
            "inspection found src/schema.js defines amount consumed by src/billing.js "
            "in a private billing response; renaming it would create a breaking "
            "internal change.",
            "inspection found src/schema.js defines amount consumed by src/billing.js "
            "in a public billing API response; renaming it to amountCents would not "
            "break compatibility.",
            "inspection found documentation quotes that src/schema.js defines amount "
            "consumed by src/billing.js in a public billing API response; renaming it "
            "would create a breaking API change.",
            "inspection found src/schema.js defines amount consumed by src/billing.js "
            "in a public billing API response; renaming it is harmless and preserves "
            "compatibility.",
            CANONICAL_PROMOTION_REASON.replace(
                "inspection found", "inspection merely found"
            ),
            CANONICAL_PROMOTION_REASON.replace("public payment", "nonpublic payment"),
            CANONICAL_PROMOTION_REASON.replace(
                "break compatibility.", "break compatibility, but this is false."
            ),
            (
                "inspection found src/schema.js defines amount but src/billing.js "
                "does not consume amount in a public billing API response surface; "
                "renaming amount to amountCents would break compatibility."
            ),
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)

    def test_escalation_promotion_rejects_negated_surface_and_path_only_billing(
        self,
    ) -> None:
        reasons = (
            "inspection found src/schema.js defines amount consumed by "
            "src/billing.js as part of the public billing API but never a response; "
            "renaming it would break compatibility.",
            "inspection found src/schema.js defines amount consumed by "
            "src/billing.js as part of the public billing API; renaming it would "
            "break compatibility but never change the response.",
            "inspection found src/schema.js defines amount consumed by "
            "src/billing.js as part of the public ledger API response surface; "
            "renaming it would break compatibility.",
            "inspection found src/schema.js defines amount consumed by "
            "src/billing.js but never as part of the public billing API; "
            "renaming it would break compatibility.",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle(
                        "cat src/schema.js src/billing.js", "inspection"
                    ),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_structured_parenthetical_is_only_observed_alias_relation(
        self,
    ) -> None:
        (self.project / "src/billing.js").write_text(
            "export const response = payment => ({ amount: payment.amount });\n"
        )
        invalid_reasons = (
            "inspection found src/schema.js defines amount consumed by src/billing.js "
            "(documentation quotes `publicPaymentResponse` returns "
            "`{ amount: payment.amount }`) as part of the public billing API payment "
            "surface; renaming amount to amountCents would break the public billing "
            "API response shape for external consumers.",
            "inspection found src/schema.js defines amount consumed by src/billing.js "
            "(`publicPaymentResponse` does not consume amount) as part of the public "
            "billing API payment surface; renaming amount to amountCents would break "
            "the public billing API response shape for external consumers.",
        )
        for reason in invalid_reasons:
            with self.subTest(reason=reason):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js", "schema"),
                    *codex_command_lifecycle("cat src/billing.js", "billing"),
                    codex_event(
                        f"Promoting to strict — {reason}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("structured promotion relation", result.stderr)

    def test_escalation_promotion_must_be_real_prose_in_a_closed_block(self) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"
        invalid_blocks = (
            f"```text\n{canonical}\n```\n{pause}",
            f"~~~transcript\n{canonical}\n~~~\n{pause}",
            f"> {canonical}\n{pause}",
            f"    {canonical}\n{pause}",
            f"Documentation example:\n{canonical}\n{pause}",
            f"Quote from a transcript:\n{canonical}\n{pause}",
        )
        for block in invalid_blocks:
            with self.subTest(block=block):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(block, item_id="promotion"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)

    def test_escalation_accepts_canonical_prose_line_plus_relevant_pause(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_multirecord_context_rejects_reviewer_mutations(self) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"

        def codex_events(texts: tuple[str, ...]) -> list[dict]:
            return [
                {"type": "thread.started", "thread_id": "thread"},
                codex_event(
                    "Mode: standard — bounded rename pending repository inspection.",
                    item_id="declaration",
                ),
                *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                *(
                    codex_event(text, item_id=f"text-{number}")
                    for number, text in enumerate(texts)
                ),
                {"type": "turn.completed", "usage": {}},
            ]

        def claude_events(texts: tuple[str, ...]) -> list[dict]:
            return [
                claude_init(),
                claude_event(
                    "Mode: standard — bounded rename pending repository inspection."
                ),
                *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
                *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": text} for text in texts
                        ],
                    },
                },
                {"type": "result", "subtype": "success", "result": "done"},
            ]

        mutations = (
            (
                "codex-backtick-fence",
                "codex",
                codex_events(("```text", canonical, "```", pause)),
            ),
            (
                "claude-tilde-fence",
                "claude",
                claude_events(("~~~transcript", canonical, "~~~", pause)),
            ),
            (
                "codex-leading-documentation-qualifier",
                "codex",
                codex_events(("Documentation example:", canonical, pause)),
            ),
            (
                "claude-trailing-quotation-qualifier",
                "claude",
                claude_events(
                    (
                        canonical,
                        "The preceding statement is only a quotation example.",
                        pause,
                    )
                ),
            ),
        )
        for name, backend, events in mutations:
            with self.subTest(name=name):
                result = self.run_validator(backend, "escalation", events)
                self.assertNotEqual(result.returncode, 0)

    def test_escalation_accepts_multirecord_canonical_promotion_then_pause(self) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(canonical, item_id="promotion"),
            codex_event(pause, item_id="pause"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_accepts_substantive_explanation_before_pause(self) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(canonical, item_id="promotion"),
            codex_event(
                "Inspection confirms that the rename is mechanically small, but "
                "the externally visible response field would change.",
                item_id="explanation",
            ),
            codex_event(
                "Should I proceed in strict mode with the public response rename?",
                item_id="pause",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_codex_trailing_qualifier_invalidates_completed_promotion(
        self,
    ) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"
        codex_prefix = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(canonical, item_id="promotion"),
            codex_event(pause, item_id="pause"),
        ]
        codex_events = [
            *codex_prefix,
            codex_event(
                "The preceding promotion statement is only an unrelated quotation.",
                item_id="qualifier",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", codex_events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-workflow prose", result.stderr)

    def test_escalation_claude_trailing_qualifier_invalidates_completed_promotion(
        self,
    ) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"
        claude_events = [
            claude_init(),
            claude_event(
                "Mode: standard — bounded rename pending repository inspection."
            ),
            *claude_read_lifecycle(self.project, "src/schema.js", "schema"),
            *claude_read_lifecycle(self.project, "src/billing.js", "billing"),
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": canonical},
                        {"type": "text", "text": pause},
                        {
                            "type": "text",
                            "text": (
                                "The preceding promotion statement is only a "
                                "documentation example."
                            ),
                        },
                    ],
                },
            },
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "escalation", claude_events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-workflow prose", result.stderr)

    def test_escalation_accepts_normal_task_prose_after_completed_promotion(
        self,
    ) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"
        codex_prefix = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(canonical, item_id="promotion"),
            codex_event(pause, item_id="pause"),
        ]
        normal_events = [
            *codex_prefix,
            codex_event(
                "An unrelated cleanup remains out of scope for this task.",
                item_id="normal-prose",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", normal_events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_split_fences_ignore_examples_but_real_demotion_rejects(self) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"

        def events_with_tail(tail: tuple[str, ...]) -> list[dict]:
            return [
                {"type": "thread.started", "thread_id": "thread"},
                codex_event(
                    "Mode: standard — bounded rename pending repository inspection.",
                    item_id="declaration",
                ),
                *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                codex_event(canonical, item_id="promotion"),
                codex_event(pause, item_id="pause"),
                *(
                    codex_event(text, item_id=f"tail-{number}")
                    for number, text in enumerate(tail)
                ),
                {"type": "turn.completed", "usage": {}},
            ]

        fenced = events_with_tail(
            ("```text", "Demoting to standard automatically.", "```")
        )
        result = self.run_validator("codex", "escalation", fenced)
        self.assertEqual(result.returncode, 0, result.stderr)

        real = events_with_tail(("Demoting to standard automatically.",))
        result = self.run_validator("codex", "escalation", real)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one workflow transition", result.stderr)

    def test_escalation_split_fence_closure_supports_multiple_fences(self) -> None:
        canonical = f"Promoting to strict — {CANONICAL_PROMOTION_REASON}"
        pause = "Should we retain the compatibility alias during migration?"
        texts = (
            "```text",
            canonical,
            "```",
            "~~~ transcript",
            "Demoting to standard automatically.",
            "~~~~",
            canonical,
            pause,
        )
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            *(
                codex_event(text, item_id=f"text-{number}")
                for number, text in enumerate(texts)
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_rejects_semantic_duplicate_promotions(self) -> None:
        duplicates = (
            "Escalating to strict because the API is breaking.",
            "Raising workflow to strict because payment compatibility is at risk.",
            "Upgrading to strict because payment compatibility is at risk.",
            "Switching to strict because the public API is affected.",
            "Moving to strict because payment compatibility is at risk.",
            "Transitioning workflow to strict because the API is breaking.",
        )
        for duplicate in duplicates:
            with self.subTest(duplicate=duplicate):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}",
                        item_id="promotion",
                    ),
                    codex_event(
                        duplicate
                        + "\nShould we retain the compatibility alias during migration?",
                        item_id="duplicate",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one workflow transition", result.stderr)

    def test_escalation_requires_one_canonical_promotion_not_only_a_synonym(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                "Escalating to strict because inspection found a public API breaking "
                "compatibility risk in payment billing.\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one canonical promotion", result.stderr)

    def test_escalation_rejects_automatic_demotion_after_promotion(self) -> None:
        demotions = (
            "Demoting to standard automatically.",
            "Lowering workflow to lean after the review.",
            "Switching to standard now.",
            "Moving to lean for implementation.",
        )
        for demotion in demotions:
            with self.subTest(demotion=demotion):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    codex_event(demotion, item_id="demotion"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one workflow transition", result.stderr)

    def test_escalation_rejects_demotion_transition_before_canonical_promotion(self) -> None:
        for transition in (
            "Downgrading to lean before reconsidering.",
            "Transitioning workflow to standard for now.",
        ):
            with self.subTest(transition=transition):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.\n"
                        + transition,
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias "
                        "during migration?",
                        item_id="promotion",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one workflow transition", result.stderr)

    def test_escalation_transition_detector_handles_modifiers_possessives_and_plurals(self) -> None:
        variants = (
            "Switching the active modes to strict because risk increased.",
            "Moving our workflow to lean after the pause.",
            "Downgrading current mode to standard before implementation.",
        )
        for variant in variants:
            with self.subTest(variant=variant):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded rename pending repository inspection.",
                        item_id="declaration",
                    ),
                    *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
                    codex_event(
                        f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                    codex_event(variant, item_id="variant"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exactly one workflow transition", result.stderr)

    def test_escalation_transition_detector_keeps_word_boundaries(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
                "Should we retain the compatibility alias during migration?",
                item_id="promotion",
            ),
            codex_event(
                "The model catalog discusses workflowish strictness and movement.",
                item_id="boundary",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_escalation_rejects_invalid_transition_order(self) -> None:
        declaration = codex_event(
            "Mode: standard — bounded rename pending repository inspection.",
            item_id="declaration",
        )
        strict_declaration = codex_event(
            "Mode: strict — payment API risk assumed before inspection.",
            item_id="declaration",
        )
        inspection = codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection")
        mutation = codex_command_lifecycle(
            "python3 -c 'open(\"src/schema.js\", \"w\").write(\"changed\")'",
            "mutation",
        )
        promotion = codex_event(
            f"Promoting to strict — {CANONICAL_PROMOTION_REASON}\n"
            "Should we retain the compatibility alias during migration?",
            item_id="promotion",
        )
        cases = (
            (
                "initial strict without inspection",
                [strict_declaration, promotion],
                "expected Mode: standard",
            ),
            (
                "promotion before inspection",
                [declaration, promotion, *inspection],
                "schema.js and src/billing.js",
            ),
            (
                "mutation before promotion",
                [declaration, *inspection, *mutation, promotion],
                "mutation before strict promotion/approval pause",
            ),
            (
                "second mode declaration",
                [
                    declaration,
                    *inspection,
                    codex_event(
                        "Mode: strict — second declaration.\n"
                        "Promoting to strict — public API breaking compatibility "
                        "risk in payment billing.\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                ],
                "exactly one assistant-visible mode declaration",
            ),
            (
                "standard execution without promotion",
                [
                    declaration,
                    *inspection,
                    codex_event(
                        "Should we retain the compatibility alias during migration?",
                        item_id="pause",
                    ),
                ],
                "workflow transition",
            ),
            (
                "promotion to non-strict",
                [
                    declaration,
                    *inspection,
                    codex_event(
                        "Promoting to lean — public API breaking compatibility risk "
                        "in payment billing.\n"
                        "Should we retain the compatibility alias during migration?",
                        item_id="promotion",
                    ),
                ],
                "promotion to strict",
            ),
        )
        for label, body, expected_error in cases:
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    *body,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "escalation", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_override_requires_risk_warning_without_mode_promotion(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit override.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_accepts_authoritative_explicit_lean_wording(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — The user explicitly requested lean mode.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verified: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_warning_is_a_closed_two_sentence_contract(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit authentication override.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

        destructive_operation = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit destructive-operation override.\n"
                "Warning: Destructive external operation is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: operation tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", destructive_operation)
        self.assertEqual(result.returncode, 0, result.stderr)

        contradictory_warning = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit authentication override.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override. "
                "I am now operating in strict mode.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", contradictory_warning)
        self.assertNotEqual(result.returncode, 0)

        trigger_injection = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit authentication override.\n"
                "Warning: I am now operating in strict mode because authentication "
                "is strict-risk work. Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", trigger_injection)
        self.assertNotEqual(result.returncode, 0)

    def test_override_allows_one_distinct_post_inspection_warning(self) -> None:
        declaration_and_warning = codex_event(
            "Mode: lean — explicit authentication override.\n"
            "Warning: Authentication is strict-risk work. "
            "Retaining your explicit lean override.",
            item_id="mode-warning",
        )
        mutation = [
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
        ]
        distinct = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration_and_warning,
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(
                "Warning: Production data migration is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="additional-warning",
            ),
            *mutation,
            codex_event("Verification: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", distinct)
        self.assertEqual(result.returncode, 0, result.stderr)

        duplicate = [
            {"type": "thread.started", "thread_id": "thread"},
            declaration_and_warning,
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="duplicate-warning",
            ),
            *mutation,
            codex_event("Verification: authentication tests pass.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", duplicate)
        self.assertNotEqual(result.returncode, 0)

    def test_override_does_not_require_a_redundant_lean_continuity_sentence(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — the user explicitly requested lean mode for this localized "
                "authentication fix.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: npm test passes.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_rejects_late_warning_promotion_or_incomplete_execution(self) -> None:
        declaration = codex_event(
            "Mode: lean — explicit authentication override.", item_id="mode"
        )
        warning = codex_event(
            "Warning: Authentication is strict-risk work. "
            "Retaining your explicit lean override.",
            item_id="warning",
        )
        mutation = [
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
        ]
        cases = (
            (
                "warning after inspection",
                [
                    declaration,
                    *codex_command_lifecycle("cat src/auth.js", "inspection"),
                    warning,
                    *mutation,
                    codex_event("Verification: authentication tests pass.", item_id="verify"),
                ],
            ),
            (
                "warning after mutation",
                [
                    declaration,
                    *mutation,
                    warning,
                    codex_event("Verification: authentication tests pass.", item_id="verify"),
                ],
            ),
            (
                "unrelated prose before warning",
                [
                    declaration,
                    codex_event(
                        "I’ll inspect the authentication code first.",
                        item_id="early-prose",
                    ),
                    warning,
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "promotion despite override",
                [
                    declaration,
                    warning,
                    codex_event(
                        "Promoting to strict — authentication is a security risk.",
                        item_id="promotion",
                    ),
                    *mutation,
                    codex_event("Verification: authentication tests pass.", item_id="verify"),
                ],
            ),
            (
                "switching mode to strict",
                [
                    declaration,
                    warning,
                    codex_event(
                        "I am switching the workflow mode to strict.",
                        item_id="strict-switch",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "escalating mode into strict",
                [
                    declaration,
                    warning,
                    codex_event(
                        "I am escalating our mode into strict.",
                        item_id="strict-escalation",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "strict mode active",
                [
                    declaration,
                    warning,
                    codex_event(
                        "Strict mode is now active.",
                        item_id="strict-active",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            *(
                (
                    f"extra transition prose: {transition}",
                    [
                        declaration,
                        warning,
                        codex_event(
                            transition,
                            item_id=f"strict-transition-{number}",
                        ),
                        *mutation,
                        codex_event(
                            "Verification: authentication tests pass.",
                            item_id="verify",
                        ),
                    ],
                )
                for number, transition in enumerate(
                    (
                        "I am now operating in strict mode.",
                        "The active mode is strict now.",
                        "I have adopted strict mode for the rest of this task.",
                        "I will proceed in strict mode.",
                    )
                )
            ),
            ("no mutation", [declaration, warning, codex_event("Verification: tests pass.", item_id="verify")]),
            ("no verification", [declaration, warning, *mutation]),
            (
                "failed verification",
                [
                    declaration,
                    warning,
                    *mutation,
                    codex_event(
                        "Verification failed: authentication tests are failing.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "negated risk warning",
                [
                    declaration,
                    codex_event(
                        "Authentication is not a strict security risk; I’ll honor "
                        "the explicit lean override.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "negated override retention",
                [
                    declaration,
                    codex_event(
                        "Authentication is a strict security risk; I will not honor "
                        "the explicit lean override.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "contracted negated risk warning",
                [
                    declaration,
                    codex_event(
                        "Authentication isn't a strict security risk; I’ll honor "
                        "the explicit lean override.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "contradictory risk warning",
                [
                    declaration,
                    codex_event(
                        "Authentication is a strict security risk; authentication "
                        "is not actually a security risk; I’ll honor the explicit "
                        "lean override.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "negated retention followed by as requested",
                [
                    declaration,
                    codex_event(
                        "Authentication is a strict security risk; I will not honor "
                        "the explicit lean override; as requested.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "rejected retention followed by as requested",
                [
                    declaration,
                    codex_event(
                        "Authentication is a strict security risk; I reject the "
                        "explicit lean override; as requested.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "non-authoritative retention followed by as requested",
                [
                    declaration,
                    codex_event(
                        "Authentication is a strict security risk; the lean override "
                        "is not authoritative; as requested.",
                        item_id="warning",
                    ),
                    *mutation,
                    codex_event(
                        "Verification: authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
            (
                "verification question",
                [
                    declaration,
                    warning,
                    *mutation,
                    codex_event("Verification: tests pass?", item_id="verify"),
                ],
            ),
            (
                "expected verification",
                [
                    declaration,
                    warning,
                    *mutation,
                    codex_event(
                        "I expect authentication tests pass.",
                        item_id="verify",
                    ),
                ],
            ),
        )
        for label, body in cases:
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    *body,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "override", events)
                self.assertNotEqual(result.returncode, 0)

    def test_override_allows_neutral_summary_before_separate_verification(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit authentication override.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event(
                "Updated the session expiry handling in src/auth.js.",
                item_id="summary",
            ),
            codex_event(
                "Verification: authentication tests pass.",
                item_id="verify",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

        negated_transition_verification = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit authentication override.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override.",
                item_id="mode-warning",
            ),
            codex_event(
                "src/auth.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/auth.js", item_type="file_change", item_id="mutation"),
            codex_event(
                "Verification: confirmed the workflow did not switch to strict "
                "mode; authentication tests passed.",
                item_id="verify",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "override", negated_transition_verification
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_standard_override_keeps_required_inline_outline(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — explicit override for a production migration.\n"
                "Warning: Production data migration is strict-risk work. "
                "Retaining your explicit standard override.",
                item_id="mode-warning",
            ),
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(
                "Implementation outline:\n"
                "- Approach: update the CLI summary calculation to total item prices.\n"
                "- Affected files: src/cli.js and test/summary.test.js.\n"
                "- Verification: run npm test and check the summary JSON count and total.",
                item_id="standard-outline",
            ),
            codex_event(
                "src/cli.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/cli.js", item_type="file_change", item_id="mutation"),
            codex_event(
                "Verification: npm test passes.",
                item_id="verify",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override-standard", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inspection_discovered_override_warns_before_readiness_and_mutation(
        self,
    ) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — explicit override for a bounded field rename.",
                item_id="mode",
            ),
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(
                "Warning: Public API compatibility is strict-risk work. "
                "Retaining your explicit standard override.",
                item_id="warning",
            ),
            codex_event(
                "Implementation outline:\n"
                "- Approach: update the CLI summary calculation to total item prices.\n"
                "- Affected files: src/cli.js and test/summary.test.js.\n"
                "- Verification: run npm test and check the summary JSON count and total.",
                item_id="standard-outline",
            ),
            codex_event(
                "src/cli.js",
                item_type="file_change",
                event_type="item.started",
                item_id="mutation",
            ),
            codex_event("src/cli.js", item_type="file_change", item_id="mutation"),
            codex_event("Verification: npm test passes.", item_id="verify"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override-discovered", events)
        self.assertEqual(result.returncode, 0, result.stderr)

        prose_before_warning = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — explicit override for a bounded field rename.",
                item_id="mode",
            ),
            *codex_command_lifecycle("cat src/schema.js", "inspection"),
            codex_event(
                "The field appears in an external response.",
                item_id="early-prose",
            ),
            *events[4:-1],
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "override-discovered", prose_before_warning
        )
        self.assertNotEqual(result.returncode, 0)

    def test_override_requires_successful_claude_mutation_result(self) -> None:
        events = [
            claude_init(),
            claude_event(
                "Mode: lean — explicit override.\n"
                "Warning: Authentication is strict-risk work. "
                "Retaining your explicit lean override."
            ),
            claude_tool_event(
                "Write",
                {
                    "file_path": str(self.project / "src/auth.js"),
                    "content": "implemented",
                },
                tool_id="failed-write",
            ),
            claude_tool_result(
                "failed-write",
                is_error=True,
                content="Permission denied.",
            ),
            claude_event("Verification: authentication tests pass."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "override", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mutation did not complete successfully", result.stderr)

    def test_explicit_skill_requires_assistant_visible_brainstorming_signal(self) -> None:
        passing = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit override.\n"
                "I am using the brainstorming skill. Two options are welcomeUser and greetUser."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "explicit-skill", passing)
        self.assertEqual(result.returncode, 0, result.stderr)

        prompt_only = [
            {"type": "user", "message": {"content": "Use the brainstorming skill"}},
            {"type": "thread.started", "thread_id": "thread"},
            codex_event("Mode: lean — explicit override.\nTwo options: welcomeUser and greetUser."),
            {"type": "turn.completed", "usage": {}},
        ]
        failing = self.run_validator("codex", "explicit-skill", prompt_only)
        self.assertNotEqual(failing.returncode, 0)
        self.assertIn("affirmative brainstorming", failing.stderr)

    def test_claude_rejects_task_tool_before_mode_declaration(self) -> None:
        events = [
            claude_init(),
            claude_tool_event("Bash", {"command": "git status --short"}),
            claude_event("Mode: lean — localized typo correction.\nVerification passed."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "lean", events, plugin_identity=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task-specific action before mode declaration", result.stderr)

    def test_claude_rejects_visible_prose_before_mode_declaration(self) -> None:
        events = [
            claude_init(),
            claude_event("I’ll inspect the project before choosing a mode."),
            claude_event(
                "Mode: lean — localized typo correction.\nVerification passed."
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "lean", events, plugin_identity=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assistant prose before mode declaration", result.stderr)

    def test_codex_allows_only_generic_bootstrap_narration_before_mode(self) -> None:
        generic = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Loading workflow-selection sources before task analysis.",
                item_id="bootstrap-note",
            ),
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Mode: lean — localized typo correction.\nVerification passed.",
                item_id="mode",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "lean", generic, inject_codex_bootstrap=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        duplicate_generic = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Loading workflow-selection sources before task analysis.",
                item_id="bootstrap-note-1",
            ),
            codex_event(
                "Loading workflow-selection sources before task analysis.",
                item_id="bootstrap-note-2",
            ),
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Mode: lean — localized typo correction.\nVerification passed.",
                item_id="mode",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "lean", duplicate_generic, inject_codex_bootstrap=False
        )
        self.assertNotEqual(result.returncode, 0)

        task_specific = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "I’ll inspect src/auth.js and change token expiry handling.",
                item_id="early-task-prose",
            ),
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Mode: lean — localized typo correction.\nVerification passed.",
                item_id="mode",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "lean", task_specific, inject_codex_bootstrap=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assistant prose before mode declaration", result.stderr)

        risk_conclusion = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "The workflow says authentication is strict-risk work.",
                item_id="early-risk-conclusion",
            ),
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Mode: lean — localized typo correction.\nVerification passed.",
                item_id="mode",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "lean", risk_conclusion, inject_codex_bootstrap=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assistant prose before mode declaration", result.stderr)

        task_specific_loading = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "I’m loading the workflow selector before fixing the "
                "authentication expiry bug.",
                item_id="task-specific-loading",
            ),
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Mode: lean — localized typo correction.\nVerification passed.",
                item_id="mode",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "lean", task_specific_loading, inject_codex_bootstrap=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assistant prose before mode declaration", result.stderr)

        task_specific_bootstrap_variants = (
            "I’m loading the workflow selector before correcting the login timeout defect.",
            "I’m using workflow selection before updating user-session lifetime handling.",
            "I’ll follow the workflow selector before changing greeting behavior.",
        )
        for number, narration in enumerate(task_specific_bootstrap_variants):
            with self.subTest(narration=narration):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        narration,
                        item_id=f"task-specific-bootstrap-{number}",
                    ),
                    *codex_bootstrap_lifecycles(),
                    codex_event(
                        "Mode: lean — localized typo correction.\n"
                        "Verification passed.",
                        item_id="mode",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator(
                    "codex", "lean", events, inject_codex_bootstrap=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("assistant prose before mode declaration", result.stderr)

        late_generic = [
            {"type": "thread.started", "thread_id": "thread"},
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Loading workflow-selection sources before task analysis.",
                item_id="late-bootstrap-note",
            ),
            codex_event(
                "Mode: lean — localized typo correction.\nVerification passed.",
                item_id="mode",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "lean", late_generic, inject_codex_bootstrap=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assistant prose before mode declaration", result.stderr)

    def test_claude_allows_selector_bootstrap_before_mode_declaration(self) -> None:
        events = [
            claude_init(),
            claude_tool_event("Skill", {"skill": "selecting-workflow-mode"}),
            claude_tool_event(
                "Read",
                {"file_path": "/expected/checkout/skills/selecting-workflow-mode/references/risk-matrix.md"},
            ),
            claude_event("Mode: lean — localized typo correction.\nVerification passed."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "lean", events, plugin_identity=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_read_bootstrap_requires_exact_expected_root(self) -> None:
        checkout = self.root / "checkout"
        selector = checkout / "skills/selecting-workflow-mode/SKILL.md"
        matrix = selector.parent / "references/risk-matrix.md"
        matrix.parent.mkdir(parents=True)
        selector.write_text("selector")
        matrix.write_text("matrix")
        alias = self.root / "checkout-alias"
        alias.symlink_to(checkout, target_is_directory=True)
        invalid_paths = (
            self.root / "wrong/skills/selecting-workflow-mode/SKILL.md",
            self.root / "checkout-evil/skills/selecting-workflow-mode/SKILL.md",
            checkout / "other/../skills/selecting-workflow-mode/SKILL.md",
            alias / "skills/selecting-workflow-mode/SKILL.md",
        )
        for path in invalid_paths:
            with self.subTest(path=path):
                events = [
                    claude_init(path=str(checkout)),
                    claude_tool_event("Read", {"file_path": str(path)}),
                    claude_event(
                        "Mode: lean — localized correction.\nVerification passed."
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude",
                    "lean",
                    events,
                    plugin_identity=True,
                    expected_plugin_root=str(checkout),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("task-specific action before mode declaration", result.stderr)

        for path in (selector, matrix):
            with self.subTest(valid_path=path):
                events = [
                    claude_init(path=str(checkout)),
                    claude_tool_event("Read", {"file_path": str(path)}),
                    claude_event(
                        "Mode: lean — localized correction.\nVerification passed."
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude",
                    "lean",
                    events,
                    plugin_identity=True,
                    expected_plugin_root=str(checkout),
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_read_rejects_symlinked_allowed_path_components(self) -> None:
        checkout = self.root / "checkout"
        selector = checkout / "skills/selecting-workflow-mode/SKILL.md"
        selector.parent.mkdir(parents=True)
        outside = self.root / "outside-selector.md"
        outside.write_text("outside")
        selector.symlink_to(outside)
        outside_references = self.root / "outside-references"
        outside_references.mkdir()
        (outside_references / "risk-matrix.md").write_text("outside")
        references = selector.parent / "references"
        references.symlink_to(outside_references, target_is_directory=True)
        for path in (selector, references / "risk-matrix.md"):
            with self.subTest(path=path):
                events = [
                    claude_init(path=str(checkout)),
                    claude_tool_event("Read", {"file_path": str(path)}),
                    claude_event(
                        "Mode: lean — localized correction.\nVerification passed."
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude",
                    "lean",
                    events,
                    plugin_identity=True,
                    expected_plugin_root=str(checkout),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "task-specific action before mode declaration", result.stderr
                )

    def test_claude_skill_bootstrap_uses_exact_names_not_suffixes(self) -> None:
        for skill in (
            "selecting-workflow-mode",
            "superpowers:selecting-workflow-mode",
        ):
            with self.subTest(valid_skill=skill):
                events = [
                    claude_init(),
                    claude_tool_event("Skill", {"skill": skill}),
                    claude_event(
                        "Mode: lean — localized correction.\nVerification passed."
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude", "lean", events, plugin_identity=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        for skill in (
            "evil:selecting-workflow-mode",
            "evil:superpowers:selecting-workflow-mode",
            "using-superpowers",
        ):
            with self.subTest(invalid_skill=skill):
                events = [
                    claude_init(),
                    claude_tool_event("Skill", {"skill": skill}),
                    claude_event(
                        "Mode: lean — localized correction.\nVerification passed."
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude", "lean", events, plugin_identity=True
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "task-specific action before mode declaration", result.stderr
                )

    def test_codex_rejects_task_command_before_mode_declaration(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "git status --short",
                item_type="command_execution",
                event_type="item.started",
            ),
            codex_event("Mode: standard — bounded CLI change.\nTests passed."),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task-specific action before mode declaration", result.stderr)

    def test_codex_allows_selector_bootstrap_before_mode_declaration(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            *codex_bootstrap_lifecycles(),
            codex_event(
                "Mode: standard — bounded CLI change.\nTests passed.",
                item_id="message",
            ),
            *codex_standard_contract_events(),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "standard", events, inject_codex_bootstrap=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_does_not_trust_reused_item_ids_before_declaration(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "git status --short",
                item_type="command_execution",
                event_type="item.started",
                item_id="__bootstrap_1",
            ),
            codex_event("Mode: standard — bounded CLI change.\nTests passed."),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("item lifecycle reused id", result.stderr)

    def test_codex_rejects_non_read_command_that_mentions_bootstrap_path(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "git status /expected/checkout/skills/selecting-workflow-mode/SKILL.md",
                item_type="command_execution",
                event_type="item.started",
            ),
            codex_event("Mode: standard — bounded CLI change.\nTests passed."),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task-specific action before mode declaration", result.stderr)

    def test_codex_bootstrap_parser_rejects_shell_and_mixed_operand_mutations(self) -> None:
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        mutations = (
            f"cat {selector} README.md",
            f"sed -i '1,2p' {selector}",
            f"cat {selector} | tee /tmp/copied",
            f"cat {selector} > /tmp/copied",
            f"cat $(printf %s {selector})",
            f"cat {selector} && cat {selector}",
            "cat /expected/checkout-evil/skills/selecting-workflow-mode/SKILL.md",
            f"/tmp/attacker/cat {selector}",
        )
        for command in mutations:
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        command,
                        item_type="command_execution",
                        event_type="item.started",
                    ),
                    codex_event("Mode: standard — bounded change.\nTests passed."),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("task-specific action before mode declaration", result.stderr)

    def test_codex_bootstrap_parser_accepts_exact_read_only_argv(self) -> None:
        using = "/expected/checkout/skills/using-superpowers/SKILL.md"
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        matrix = (
            "/expected/checkout/skills/selecting-workflow-mode/"
            "references/risk-matrix.md"
        )
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            *codex_command_lifecycle(f"cat {using}", "using"),
            *codex_command_lifecycle(
                f"/bin/zsh -lc \"sed -n '1,260p' {selector}\"", "selector"
            ),
            *codex_command_lifecycle(f"cat {matrix}", "matrix"),
            codex_event(
                "Mode: standard — bounded change.\nTests passed.",
                item_id="message",
            ),
            *codex_standard_contract_events(),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "standard", events, inject_codex_bootstrap=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_bootstrap_requires_exact_successful_standalone_sequence(self) -> None:
        using = "/expected/checkout/skills/using-superpowers/SKILL.md"
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        matrix = (
            "/expected/checkout/skills/selecting-workflow-mode/"
            "references/risk-matrix.md"
        )
        cases = (
            (
                "combined reads",
                [
                    *codex_command_lifecycle(f"cat {using}", "using"),
                    *codex_command_lifecycle(
                        f"cat {selector} {matrix}", "combined"
                    ),
                ],
            ),
            (
                "wrong order",
                [*codex_command_lifecycle(f"cat {selector}", "selector")],
            ),
            (
                "missing matrix",
                [
                    *codex_command_lifecycle(f"cat {using}", "using"),
                    *codex_command_lifecycle(f"cat {selector}", "selector"),
                ],
            ),
            (
                "duplicate",
                [
                    *codex_command_lifecycle(f"cat {using}", "using"),
                    *codex_command_lifecycle(f"cat {using}", "duplicate"),
                ],
            ),
            (
                "failed read",
                [*codex_command_lifecycle(f"cat {using}", "using", exit_code=1)],
            ),
        )
        for label, bootstrap in cases:
            with self.subTest(label=label):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    *bootstrap,
                    codex_event(
                        "Mode: standard — bounded change.\nTests passed.",
                        item_id="message",
                    ),
                    *codex_standard_contract_events(),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator(
                    "codex",
                    "standard",
                    events,
                    inject_codex_bootstrap=False,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_codex_rejects_invalid_item_lifecycle(self) -> None:
        using = "/expected/checkout/skills/using-superpowers/SKILL.md"
        bootstrap = f"cat {using}"
        mutations = (
            [codex_event(bootstrap, item_type="command_execution", item_id="a")],
            [
                codex_event(
                    bootstrap,
                    item_type="command_execution",
                    event_type="item.updated",
                    item_id="a",
                )
            ],
            [
                *codex_command_lifecycle(bootstrap, "a"),
                codex_event(
                    bootstrap,
                    item_type="command_execution",
                    event_type="item.started",
                    item_id="a",
                ),
            ],
            [
                codex_event(
                    bootstrap,
                    item_type="command_execution",
                    event_type="item.started",
                    item_id="a",
                ),
                codex_event(
                    bootstrap,
                    item_type="command_execution",
                    event_type="item.started",
                    item_id="a",
                ),
            ],
        )
        for lifecycle in mutations:
            with self.subTest(lifecycle=lifecycle):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded change.\nTests passed.",
                        item_id="message",
                    ),
                    *lifecycle,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("item lifecycle", result.stderr)

    def test_codex_updated_and_completed_actions_are_revalidated(self) -> None:
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        bootstrap = f"cat {selector}"
        for event_type in ("item.updated", "item.completed"):
            with self.subTest(event_type=event_type):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: standard — bounded change.\nTests passed.",
                        item_id="message",
                    ),
                    codex_event(
                        bootstrap,
                        item_type="command_execution",
                        event_type="item.started",
                        item_id="a",
                    ),
                    codex_event(
                        "git status --short",
                        item_type="command_execution",
                        event_type=event_type,
                        item_id="a",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("item lifecycle changed immutable payload", result.stderr)

    def test_codex_accepts_consistent_updated_item_lifecycle(self) -> None:
        using = "/expected/checkout/skills/using-superpowers/SKILL.md"
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        matrix = (
            "/expected/checkout/skills/selecting-workflow-mode/"
            "references/risk-matrix.md"
        )
        bootstrap = f"cat {using}"
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                bootstrap,
                item_type="command_execution",
                event_type="item.started",
                item_id="a",
            ),
            codex_event(
                bootstrap,
                item_type="command_execution",
                event_type="item.updated",
                item_id="a",
            ),
            codex_event(
                bootstrap,
                item_type="command_execution",
                item_id="a",
                exit_code=0,
            ),
            *codex_command_lifecycle(f"cat {selector}", "selector"),
            *codex_command_lifecycle(f"cat {matrix}", "matrix"),
            codex_event(
                "Mode: standard — bounded change.\nTests passed.",
                item_id="message",
            ),
            *codex_standard_contract_events(),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "standard", events, inject_codex_bootstrap=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_accepts_full_matrix_parallel_item_lifecycles(self) -> None:
        standard_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — this is a bounded, reversible CLI behavior "
                "change requiring a small design choice and regression coverage.",
                item_id="item_4",
            ),
            codex_event(
                "/bin/zsh -lc \"sed -n '1,240p' items.json\"",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_9",
            ),
            codex_event(
                "/bin/zsh -lc \"sed -n '1,240p' package.json\"",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_10",
            ),
            codex_event(
                "/bin/zsh -lc \"sed -n '1,240p' items.json\"",
                item_type="command_execution",
                item_id="item_9",
                exit_code=0,
            ),
            codex_event(
                "/bin/zsh -lc \"sed -n '1,240p' package.json\"",
                item_type="command_execution",
                item_id="item_10",
                exit_code=0,
            ),
            codex_event(
                "Implementation outline:\n\n"
                "- Approach: add a summary command that reads items.json and "
                "computes count and total.\n"
                "- Affected files: src/cli.js and test/summary.test.js.\n"
                "- Verification: run npm test and invoke the CLI, checking its "
                "JSON output for count and total.",
                item_id="item_14",
            ),
            codex_event(
                "src/cli.js",
                item_type="file_change",
                event_type="item.started",
                item_id="item_20",
            ),
            codex_event(
                "src/cli.js", item_type="file_change", item_id="item_20"
            ),
            codex_event(
                "Implemented the `summary` command.\n\nVerified:\n\n- `npm test` — "
                "1 test passed",
                item_id="item_26",
            ),
            {"type": "turn.completed", "usage": {}},
        ]

        strict_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: strict — this request combines a production payment-data "
                "migration with a breaking public API change.",
                item_id="item_4",
            ),
            {"type": "item.started", "item": {"id": "item_7", "type": "todo_list"}},
            codex_event(
                "I’ll inspect the repository structure, existing payment model/API, "
                "tests, and recent history. I’m only gathering context at this stage; "
                "the strict workflow blocks code changes until the design is approved.",
                item_id="item_8",
            ),
            codex_event(
                "/bin/zsh -lc \"rg -n -i payment .\"",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_9",
            ),
            codex_event(
                "/bin/zsh -lc \"rg --files | sed -n '1,240p'\"",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_10",
            ),
            codex_event(
                "/bin/zsh -lc \"rg -n -i payment .\"",
                item_type="command_execution",
                item_id="item_9",
            ),
            codex_event(
                "/bin/zsh -lc \"rg --files | sed -n '1,240p'\"",
                item_type="command_execution",
                item_id="item_10",
            ),
            codex_event(
                "/bin/zsh -lc 'git log -5 --oneline --decorate'",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_11",
            ),
            codex_event(
                "/bin/zsh -lc 'git status --short'",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_12",
            ),
            codex_event(
                "/bin/zsh -lc 'git status --short'",
                item_type="command_execution",
                item_id="item_12",
            ),
            codex_event(
                "/bin/zsh -lc 'git log -5 --oneline --decorate'",
                item_type="command_execution",
                item_id="item_11",
            ),
            codex_event(
                "The repository currently contains only a README—no schema, API, "
                "runtime, or deployment context—so the design must establish the "
                "contract first.\n\nWhich public API transition do you want?\n\n"
                "1. **Versioned API (recommended):** keep the dollar-based endpoint "
                "temporarily; introduce a new version using integer cents.\n"
                "2. **New field:** add `amount_cents`, deprecate the dollar field, "
                "then remove it later.\n"
                "3. **In-place breaking change:** keep the existing field name but "
                "change its meaning from dollars to cents in one coordinated release.",
                item_id="item_14",
            ),
            {"type": "item.completed", "item": {"id": "item_7", "type": "todo_list"}},
            {"type": "turn.completed", "usage": {}},
        ]

        explicit_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — the user explicitly selected lean for a read-only, "
                "localized naming exploration.",
                item_id="item_4",
            ),
            codex_event(
                "The mode is active. The brainstorming skill now guides a small "
                "design comparison only; it will not result in edits.",
                item_id="item_5",
            ),
            {"type": "item.started", "item": {"id": "item_7", "type": "todo_list"}},
            codex_event(
                "/bin/zsh -lc \"rg --files | sed -n '1,160p'\"",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_8",
            ),
            codex_event(
                "/bin/zsh -lc \"rg --files | sed -n '1,160p'\"",
                item_type="command_execution",
                item_id="item_8",
            ),
            codex_event(
                "The current function is `greet(name) => \"Hello <name>\"`.\n\n"
                "Should its name emphasize:\n\n- the action of greeting, or\n- "
                "that it returns/formats a greeting string?",
                item_id="item_11",
            ),
            {"type": "item.completed", "item": {"id": "item_7", "type": "todo_list"}},
            {"type": "turn.completed", "usage": {}},
        ]

        for case, events in (("standard", standard_events), ("strict", strict_events)):
            with self.subTest(case=case):
                result = self.run_validator("codex", case, events)
                self.assertEqual(result.returncode, 0, result.stderr)

        explicit_result = self.run_validator(
            "codex", "explicit-skill", explicit_events
        )
        self.assertNotEqual(explicit_result.returncode, 0)
        self.assertIn("two distinct positive options", explicit_result.stderr)
        self.assertNotIn("item lifecycle", explicit_result.stderr)

    def test_strict_requires_a_relevant_question_or_approval_request(self) -> None:
        for text in (
            "Mode: strict — migration design is complete. Done.",
            "Mode: strict — migration design is complete. What time is it?",
            "Mode: strict — migration design is complete. Do you like this API?",
            "Mode: strict — migration design is complete. What do you like about this API?",
            "Mode: strict — migration design is complete. Do you approve this API?",
            "Mode: strict — migration design is complete. Please approve lunch.",
            "Mode: strict — migration design is complete. Please approve lunch before implementation.",
            "Mode: strict — migration design is complete. Please confirm API.",
            "Mode: strict — migration design is complete. What seems nicest about this API migration approach?",
            "Mode: strict — migration design is complete. Which migration approach do you like?",
            "Mode: strict — migration design is complete. Which scopeCreep should we discuss for lunch?",
            "Mode: strict — migration design is complete. Which API contractLunch should I choose?",
            "Mode: strict — migration design is complete. I approve this API design.",
            "Mode: strict — migration design is complete. We confirm API compatibility.",
            "Mode: strict — migration design is complete. I approve this API design?",
            "Mode: strict — migration design is complete. Should I proceed in strict mode?",
            "Mode: strict — migration design is complete. Should I proceed in strict mode with lunch?",
            "Mode: strict — migration design is complete. Is strict mode relevant to the API?",
            "Mode: strict — migration design is complete. Do you approve this API in strict mode?",
            "Mode: strict — migration design is complete. What does the payment system look like today?",
        ):
            with self.subTest(text=text):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(text),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "strict", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("relevant clarification/approval pause", result.stderr)

    def test_strict_accepts_concrete_decision_or_requirement_questions(self) -> None:
        questions = (
            "Which rollback requirement applies to this migration?",
            "Which migration approach should I use?",
            "Which named option blue do you prefer?",
            "Should we use migration plan alpha?",
            "Do you want me to preserve API compatibility?",
            "Would you like us to use rollout option blue?",
            "Can you confirm whether existing API clients must retain the alias?",
            "Could you approve this API contract change?",
            "Please approve the proposed payment migration plan before implementation.",
            "Please choose named option blue for the schema conversion.",
            "Please confirm API compatibility before implementation.",
            "I need your approval on the API contract change before proceeding.",
            "I await your decision about the migration approach before proceeding.",
        )
        for question in questions:
            with self.subTest(question=question):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(f"Mode: strict — payment migration.\n{question}"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "strict", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_strict_accepts_preserved_real_decision_phrasings(self) -> None:
        phrasings = (
            "First decision: must existing API clients continue working during a "
            "deprecation window, or may the cents-based API be an immediate "
            "breaking release?",
            "Should the old amount key be removed immediately, or temporarily "
            "retained as a compatibility alias alongside amountCents?",
        )
        for phrasing in phrasings:
            with self.subTest(phrasing=phrasing):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(f"Mode: strict — payment migration.\n{phrasing}"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "strict", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_strict_accepts_final_declarative_design_approval_pause(self) -> None:
        # Exact decisive excerpts from final-0e112a1 Claude strict output.
        design = (
            "Mode: strict — production data migration mutating stored payment data "
            "plus a public API contract change; irreversible-risk, behavior-changing work.\n\n"
            "## Approaches considered\n\n"
            "**Storage migration**\n"
            "- **A. Expand → migrate → contract (recommended).** Add an "
            "`amount_cents BIGINT` column, dual-write, backfill, verify, then flip reads.\n"
            "- **B. In-place rewrite during a maintenance window.** Simple, but "
            "rollback after partial failure is dangerous and not acceptable for payments.\n\n"
            "**Public API change**\n"
            "- **A. Versioned rollout (recommended).** v2 uses integer "
            "`amount_cents`; v1 continues serving dollars through a deprecation window.\n"
            "- **B. Big-bang field change.** Rejected because unnoticed clients "
            "could overcharge by 100×.\n\n"
            "## Recommended design\n"
            "Use an idempotent batched backfill, aggregate verification, a feature-flag "
            "read flip, and a versioned API rollout with rollback at every phase.\n\n"
            "Waiting on your approval before proceeding."
        )
        events = [claude_init(), claude_event(design), {"type": "result", "subtype": "success", "result": "done"}]
        result = self.run_validator("claude", "strict", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_strict_declarative_pause_requires_design_options_and_no_mutation(self) -> None:
        bare = [
            claude_init(),
            claude_event(
                "Mode: strict — payment migration. Waiting on your approval before proceeding."
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", bare)
        self.assertNotEqual(result.returncode, 0)

        mutated = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk.\n"
                "Approaches considered:\n"
                "- A. Expand and backfill the amount_cents schema safely.\n"
                "- B. Rewrite payment rows in place with rollback risk.\n"
                "Recommended design: choose A with a versioned public API."
            ),
            claude_tool_event(
                "Write",
                {"file_path": str(self.project / "src/schema.js"), "content": "changed"},
                tool_id="mutation",
            ),
            claude_event("Waiting on your approval before proceeding."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", mutated)
        self.assertNotEqual(result.returncode, 0)

        bash_mutated = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk.\n"
                "Approaches considered:\n"
                "- A. Expand and backfill the amount_cents schema safely.\n"
                "- B. Rewrite payment rows in place with rollback risk.\n"
                "Recommended design: choose A with a versioned public API."
            ),
            claude_tool_event(
                "Bash",
                {"command": "printf changed > src/schema.js"},
                tool_id="bash-mutation",
            ),
            claude_event("Waiting on your approval before proceeding."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", bash_mutated)
        self.assertNotEqual(result.returncode, 0)

        unknown_tool = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk.\n"
                "Approaches considered:\n"
                "- A. Expand and backfill the amount_cents schema safely.\n"
                "- B. Rewrite payment rows in place with rollback risk.\n"
                "Recommended design: choose A with a versioned public API."
            ),
            claude_tool_event("UnknownWriter", {}, tool_id="unknown"),
            claude_event("Waiting on your approval before proceeding."),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", unknown_tool)
        self.assertNotEqual(result.returncode, 0)

        for pause in (
            "I am not waiting for your approval before proceeding.",
            "I am not currently waiting for your approval before proceeding.",
            "I am not actually waiting for your approval before proceeding.",
            "I intend not to wait for your approval before proceeding.",
            "I have no intention of waiting for your approval before proceeding.",
            "I am unwilling to wait for your approval before proceeding.",
            "Without waiting for your approval before proceeding.",
            "I won't wait for your approval before proceeding.",
            "I refuse to wait for your approval before proceeding.",
            "I do not plan to wait for your approval before proceeding.",
        ):
            with self.subTest(pause=pause):
                negated_pause = [
                    claude_init(),
                    claude_event(
                        "Mode: strict — production payment migration and public API risk.\n"
                        "Approaches considered:\n"
                        "- A. Expand and backfill the amount_cents schema safely.\n"
                        "- B. Rewrite payment rows in place with rollback risk.\n"
                        "Recommended design: choose A with a versioned public API.\n"
                        f"{pause}"
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "strict", negated_pause)
                self.assertNotEqual(result.returncode, 0)

        for trailing in (
            "Actually, I am proceeding without approval.",
            "Implementation starts now.",
        ):
            with self.subTest(trailing=trailing):
                trailing_after_pause = [
                    claude_init(),
                    claude_event(
                        "Mode: strict — production payment migration and public API risk.\n"
                        "Approaches considered:\n"
                        "- A. Expand and backfill the amount_cents schema safely.\n"
                        "- B. Rewrite payment rows in place with rollback risk.\n"
                        "Recommended design: choose A with a versioned public API.\n"
                        "Waiting on your approval before proceeding.\n"
                        f"{trailing}"
                    ),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude", "strict", trailing_after_pause
                )
                self.assertNotEqual(result.returncode, 0)

    def test_strict_rejects_mutation_before_any_pause_route(self) -> None:
        for pause in (
            "Should I proceed with the payment migration approach?",
            "I need your approval on the API contract change before proceeding.",
        ):
            with self.subTest(pause=pause):
                events = [
                    claude_init(),
                    claude_event(
                        "Mode: strict — production payment migration and public API risk."
                    ),
                    claude_tool_event(
                        "Write",
                        {
                            "file_path": str(self.project / "src/schema.js"),
                            "content": "changed",
                        },
                        tool_id="mutation",
                    ),
                    claude_event(pause),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "strict", events)
                self.assertNotEqual(result.returncode, 0)

    def test_strict_validates_read_probe_result_for_missing_project_path(self) -> None:
        events = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/missing.js")},
                tool_id="missing-read",
            ),
            claude_tool_result(
                "missing-read",
                is_error=True,
                content="File does not exist.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", events)
        self.assertEqual(result.returncode, 0, result.stderr)

        false_success = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/missing.js")},
                tool_id="missing-read",
            ),
            claude_tool_result(
                "missing-read",
                is_error=False,
                content="Claimed success despite missing file.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", false_success)
        self.assertNotEqual(result.returncode, 0)

        duplicate_tool_use = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/missing.js")},
                tool_id="missing-read",
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/missing-again.js")},
                tool_id="missing-read",
            ),
            claude_tool_result(
                "missing-read",
                is_error=True,
                content="File does not exist.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", duplicate_tool_use)
        self.assertNotEqual(result.returncode, 0)

        opposing_results = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/missing.js")},
                tool_id="missing-read",
            ),
            claude_tool_result(
                "missing-read",
                is_error=True,
                content="File does not exist.",
            ),
            claude_tool_result(
                "missing-read",
                is_error=False,
                content="Claimed success after the failure.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", opposing_results)
        self.assertNotEqual(result.returncode, 0)

        ghost_result = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_result(
                "ghost-read",
                is_error=True,
                content="No matching tool use.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", ghost_result)
        self.assertNotEqual(result.returncode, 0)

        early_result = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_result(
                "missing-read",
                is_error=True,
                content="Result arrived before the tool use.",
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/missing.js")},
                tool_id="missing-read",
            ),
            claude_tool_result(
                "missing-read",
                is_error=True,
                content="File does not exist.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", early_result)
        self.assertNotEqual(result.returncode, 0)

        malformed_success_result = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk."
            ),
            claude_tool_event(
                "Read",
                {"file_path": str(self.project / "src/schema.js")},
                tool_id="schema-read",
            ),
            claude_tool_result(
                "schema-read",
                is_error=[],
                content="Malformed success status.",
            ),
            claude_event("Which rollback requirement applies to this migration?"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", malformed_success_result)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_strict_declarative_pause_allows_nonmutating_approval_tool(self) -> None:
        events = [
            claude_init(),
            claude_event(
                "Mode: strict — production payment migration and public API risk.\n"
                "Approaches considered:\n"
                "- A. Expand and backfill the amount_cents schema safely.\n"
                "- B. Rewrite payment rows in place with rollback risk.\n"
                "Recommended design: choose A with a versioned public API.\n"
                "I’m stopping for your approval before proceeding."
            ),
            claude_tool_event(
                "AskUserQuestion",
                {"question": "Approve the recommended migration design?"},
                tool_id="approval",
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_strict_accepts_targeted_current_system_requirement_question(self) -> None:
        # Preserved from /tmp/superpowers-mode-evals/task1-followup-targeted-0a49b1c/
        # claude/claude-fable-5/strict/20260721T074747Z-55633-1488/assistant.txt
        events = [
            claude_init(),
            claude_event(
                "Mode: strict — payments, production data migration, and a "
                "breaking public API change are explicit strict-risk triggers.\n\n"
                "Per the strict workflow, I'll start with the brainstorming skill "
                "before designing."
            ),
            claude_event(
                "The repo turns out to be nearly empty — just a README reading "
                "\"payment migration fixture.\" There's no existing payment code, "
                "schema, or API to inspect, so the design has to be grounded in a "
                "few facts about your actual system.\n\n"
                "First question, since it shapes everything else (migration "
                "mechanics, rollout, and API versioning):\n\n"
                "**What does the payment system look like today?** Specifically, "
                "which of these best matches:\n\n"
                "- **A.** Relational DB (Postgres/MySQL) with amounts in a "
                "`DECIMAL`/`NUMERIC` dollars column, REST API returning decimal "
                "dollar amounts, external API consumers we don't control\n"
                "- **B.** Same as A, but all API consumers are internal/first-party\n"
                "- **C.** Document store (Mongo/Dynamo) with float or decimal "
                "dollar amounts\n"
                "- **D.** Something else — tell me the DB, the amount column type, "
                "the API shape, and who consumes it"
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "strict", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_strict_accepts_final_matrix_concrete_discovery_pauses(self) -> None:
        # Exact visible output from /tmp/superpowers-mode-evals/task1-final-full-a409482/
        # claude/claude-fable-5/strict/20260721T082433Z-79066-424/assistant.txt
        claude_output = (
            "Mode: strict — Payments data migration in production with a breaking "
            "public API change hits multiple strict triggers (payments/finance, "
            "production data migration, breaking compatibility).\n\n"
            "Per the strict workflow, I'll start with the brainstorming skill to "
            "explore the design before writing a plan.\n\n"
            "The brainstorming skill is active. First step is exploring the project "
            "context (read-only), then I'll refine the design through questions "
            "before any changes.\n\n"
            "The repo is essentially empty — just a README marking it as a "
            "\"payment migration fixture,\" with no application code, schema, or "
            "API definitions to inspect. So the design will be built from your "
            "requirements rather than from existing code, and I need to pin down "
            "the context before proposing approaches.\n\n"
            "One question at a time, starting with the most load-bearing:\n\n"
            "**Where does the system being migrated live, and what's the stack?** "
            "Since this repo has no code, which of these matches your situation?\n\n"
            "- **A)** An existing production system elsewhere (e.g., Postgres/MySQL "
            "+ a REST API service) — this repo is where the migration scripts, API "
            "changes, and design docs should be authored. If so, what's the database "
            "and API framework?\n"
            "- **B)** This repo should contain a representative reference "
            "implementation — schema, migration scripts, and API — that demonstrates "
            "the full migration design end to end.\n"
            "- **C)** You want a design document / runbook only (no code), covering "
            "the migration strategy, API versioning, and rollout plan.\n\n"
            "If A, please also share: the database engine, the current amount column "
            "type (e.g., `DECIMAL(10,2)`, `FLOAT`), approximate row count, and whether "
            "zero-downtime is required."
        )
        claude_events = [
            claude_init(),
            claude_event(claude_output),
            {"type": "result", "subtype": "success", "result": "done"},
        ]

        # Exact visible output from /tmp/superpowers-mode-evals/task1-final-full-a409482/
        # codex/gpt-5.6-sol/strict/20260721T082943Z-90346-6117/assistant.txt
        codex_outputs = (
            "I’m using the workflow-selection skill first because this is a high-risk "
            "production schema and public API change. I’ll determine the required "
            "safeguards before inspecting or changing the project.",
            "Mode: strict — this changes payments, production data, and a public "
            "compatibility surface.",
            "I’m using the brainstorming skill to turn the migration into a safe "
            "rollout design before implementation; its decisions will govern "
            "compatibility, backfill, and rollback.",
            "I’ll now map the existing storage model, API contract, tests, and recent "
            "changes. I’ll keep the repository read-only until you approve a concrete "
            "migration design.",
            "The repository is an empty fixture, so there’s no existing schema or API "
            "contract to infer.\n\n"
            "What should the new public API expose?\n\n"
            "1. `amount_cents` as an integer, replacing `amount` — recommended.\n"
            "2. `amount` remains the field name but changes from dollars to integer "
            "cents.\n"
            "3. A versioned API (`v2`) introduces `amount_cents`, while `v1` remains "
            "temporarily compatible.",
        )
        codex_events = [
            {"type": "thread.started", "thread_id": "thread"},
            *(
                codex_event(output, item_id=f"message-{index}")
                for index, output in enumerate(codex_outputs[1:], start=1)
            ),
            {"type": "turn.completed", "usage": {}},
        ]

        for backend, events in (("claude", claude_events), ("codex", codex_events)):
            with self.subTest(backend=backend):
                result = self.run_validator(backend, "strict", events)
                self.assertEqual(result.returncode, 0, result.stderr)

        incomplete_discovery = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: strict — payments production migration and public API risk.\n"
                "What should the API expose?\n"
                "1. `amount_cents` as an integer."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "strict", incomplete_discovery)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relevant clarification/approval pause", result.stderr)

        reviewer_adversarials = (
            "Does the API exist?\n1. No API.\n2. No schema.",
            "What should the public API expose?\n1. API\n1. API",
            "Is the system okay?\n1. API\n2. schema",
            "What should the public API expose?\n"
            "1. Review API docs.\n"
            "2. Inspect API schema.",
            "What should the public API expose?\n"
            "1. API documentation.\n"
            "2. API schema.",
            "What should the public API expose?\n"
            "1. Use API documentation.\n"
            "2. Use API schema.",
            "What should the public API expose?\n"
            "1. API docs.\n"
            "2. API schema.",
        )
        for discovery in reviewer_adversarials:
            with self.subTest(discovery=discovery):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: strict — payments production migration and public "
                        f"API risk.\n{discovery}"
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "strict", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "relevant clarification/approval pause", result.stderr
                )

        valid_post_question_cases = (
            (
                "1. Review the README.\n"
                "2. Inspect the repository.\n"
                "What should the public API expose?\n"
                "1. `amount_cents` as an integer.\n"
                "2. A versioned API introduces `amount_cents`."
            ),
            (
                "What architecture should the public API use?\n"
                "1. A versioned API exposes `amount_cents`.\n"
                "2. No public API; use an internal migration runbook."
            ),
            (
                "What architecture should the public API use?\n"
                "1. A REST interface backed by the payment database.\n"
                "2. An internal migration runbook with no external endpoint."
            ),
            (
                "What should the public API expose?\n"
                "1. `amount_cents` as an integer.\n"
                "2. A versioned API introduces `amount_cents`.\n\n"
                "Next steps:\n"
                "1. Update the CLI implementation.\n"
                "2. Run the regression tests."
            ),
        )
        for discovery in valid_post_question_cases:
            with self.subTest(valid_discovery=discovery):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: strict — payments production migration and public "
                        f"API risk.\n{discovery}"
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "strict", events)
                self.assertEqual(result.returncode, 0, result.stderr)

        pre_question_only = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: strict — payments production migration and public API risk.\n"
                "1. `amount_cents` as an integer.\n"
                "2. A versioned API introduces `amount_cents`.\n"
                "What should the public API expose?"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "strict", pre_question_only)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relevant clarification/approval pause", result.stderr)

    def test_escalation_requires_a_relevant_question_or_approval_request(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}",
                item_id="promotion",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relevant clarification/approval pause", result.stderr)

    def test_escalation_rejects_vague_strict_api_approval_question(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle("cat src/schema.js src/billing.js", "inspection"),
            codex_event(
                f"Promoting to strict — {CANONICAL_PROMOTION_REASON}",
                item_id="promotion",
            ),
            codex_event(
                "Do you approve this API in strict mode?",
                item_id="vague-pause",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relevant clarification/approval pause", result.stderr)

    def test_explicit_skill_rejects_negated_use_and_one_candidate(self) -> None:
        cases = (
            "I am not using the brainstorming skill. Options are welcomeUser and greetUser.",
            "I am using, but not actually invoking, the brainstorming skill. Options are welcomeUser and greetUser.",
            "I am using the brainstorming skill. The candidate is welcomeUser.",
        )
        for detail in cases:
            with self.subTest(detail=detail):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(f"Mode: lean — explicit override.\n{detail}"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)

    def test_explicit_skill_counts_only_positively_presented_options(self) -> None:
        details = (
            "I am using the brainstorming skill. Current identifiers are greet and name. Candidate: welcomeUser.",
            "I am using the brainstorming skill.\n- Option 1: welcomeUser\n- Option 2: greetUser (rejected)",
            "I am using the brainstorming skill. One option is welcomeUser; do not use greetUser.",
            "I am using the brainstorming skill.\nRejected candidate: currentName\nCandidate: welcomeUser",
            "I am using the brainstorming skill.\nAvoid option: currentName\nOption: welcomeUser",
            "I am using the brainstorming skill.\n~~Option: currentName~~\nOption: welcomeUser",
            "I am using the brainstorming skill.\nCurrent-only option: currentName\nOption: welcomeUser",
        )
        for detail in details:
            with self.subTest(detail=detail):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(f"Mode: lean — explicit override.\n{detail}"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("two distinct positive", result.stderr)

    def test_explicit_skill_accepts_two_structured_positive_options(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit override.\n"
                "I am using the brainstorming skill.\n"
                "1. Option: welcomeUser\n"
                "2. Option: greetUser"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "explicit-skill", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_skill_accepts_applying_and_applied_with_final_polarity(self) -> None:
        # Exact affirmative wording from final-0e112a1 Codex explicit-skill.
        for verb in ("applying", "applied"):
            with self.subTest(verb=verb):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: lean — The user explicitly requested lean mode for "
                        "a read-only, low-impact naming exploration.\n"
                        f"I’m now {verb} the requested brainstorming skill; it will "
                        "shape the naming comparison.\n"
                        "Two options are `greet` and `formatGreeting`.",
                        item_id="result",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_skill_rejects_negated_applying_or_applied_wording(self) -> None:
        details = (
            "I’m not applying the requested brainstorming skill.",
            "I never applied the brainstorming skill.",
            "I applied the brainstorming skill, but I’m not applying it after all.",
            "I applied the brainstorming skill. I am no longer applying the brainstorming skill.",
            "I applied the brainstorming skill. I stopped applying the brainstorming skill.",
            "I applied the brainstorming skill. I've stopped using the brainstorming skill.",
            "I applied the brainstorming skill. I’ve stopped using the brainstorming skill.",
            "I applied the brainstorming skill. I am no longer currently applying the brainstorming skill.",
            "I applied the brainstorming skill. I ceased applying the brainstorming skill.",
            "I applied the brainstorming skill. We've ceased applying the brainstorming skill.",
            "I applied the brainstorming skill. I haven't used the brainstorming skill after all.",
            "I applied the brainstorming skill. I've discontinued using the brainstorming skill.",
            "I applied the brainstorming skill. I'm done using the brainstorming skill.",
            "I applied the brainstorming skill. Without applying the brainstorming skill now.",
            "I applied the brainstorming skill. We aren't using the brainstorming skill anymore.",
        )
        for detail in details:
            with self.subTest(detail=detail):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: lean — explicit override.\n"
                        f"{detail}\nTwo options are `greet` and `formatGreeting`.",
                        item_id="result",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("affirmative brainstorming", result.stderr)

    def test_explicit_skill_does_not_parse_prose_first_words_as_names(self) -> None:
        adversarial = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit read-only naming exploration.\n"
                "I am using the brainstorming skill.\n"
                "Option 1: action of greeting\n"
                "Option 2: returned string"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "explicit-skill", adversarial)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("two distinct positive options", result.stderr)

        positives = (
            "Option 1: `greet` matches the action.\n"
            "Option 2: `greeting` matches the value.",
            "Option 1: greet\nOption 2: greeting",
            "Option 1: greet — action-oriented\n"
            "Option 2: greeting: value-oriented",
        )
        for candidate_text in positives:
            with self.subTest(candidates=candidate_text):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: lean — explicit read-only naming exploration.\n"
                        "I am using the brainstorming skill.\n"
                        f"{candidate_text}"
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_skill_accepts_targeted_ordered_backticked_names(self) -> None:
        # Preserved from /tmp/superpowers-mode-evals/task1-followup-targeted-0a49b1c/
        # codex/gpt-5.6-sol/explicit-skill/20260721T075013Z-57212-15118/assistant.txt
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — the user explicitly requested a read-only, tightly "
                "scoped naming exploration.\n\n"
                "The brainstorming skill now guides the naming comparison; this "
                "is the point where it shapes the work, and no files will be touched.\n\n"
                "Two good options:\n\n"
                "1. `greet` — concise and natural. Best if the function remains a "
                "tiny, obvious helper.\n"
                "2. `formatGreeting` — explicitly signals that it returns text "
                "rather than displaying or sending anything, but is more verbose.\n\n"
                "Should the name optimize for brevity (`greet`) or explicit return "
                "behavior (`formatGreeting`)? No files changed."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "explicit-skill", events)
        self.assertEqual(result.returncode, 0, result.stderr)

        conceptual_bullets = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit read-only naming exploration.\n"
                "I am using the brainstorming skill.\n"
                "1. action of greeting — concise\n"
                "2. returned string — explicit"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "explicit-skill", conceptual_bullets
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("two distinct positive options", result.stderr)

    def test_claude_accepts_full_matrix_explicit_skill_invocation(self) -> None:
        events = [
            claude_init(),
            claude_event(
                "Mode: lean — User explicitly forced lean; naming exploration is "
                "read-only with no file changes.\n\n"
                "You explicitly requested the brainstorming skill, so it runs "
                "without changing the active mode."
            ),
            claude_tool_event(
                "Skill",
                {
                    "skill": "superpowers:brainstorming",
                    "args": "Explore two possible names for the greeting function; "
                    "do not change files",
                },
                tool_id="brainstorming",
            ),
            claude_tool_result(
                "brainstorming",
                content="Launching skill: superpowers:brainstorming",
            ),
            claude_event(
                "The brainstorming skill is active. First step is exploring the "
                "project context to see what the greeting function currently looks like."
            ),
            claude_event(
                "Context explored: the project is a single file, "
                "`src/greeting.js:1`, containing the `greet` function. No callers, "
                "docs, or tests exist yet, so a rename has zero blast radius.\n\n"
                "Here are two candidate names, per your request:\n\n"
                "**Option 1: `greet` (keep the current name)**\n"
                "A verb, which matches what the function does.\n\n"
                "**Option 2: `greeting` (noun form, matching the filename)**\n"
                "A noun describing what the function returns.\n\n"
                "No files were changed. Let me know which name you'd like."
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "explicit-skill", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_skill_accepts_final_matrix_read_only_shell_composition(self) -> None:
        (self.project / "src/greeting.js").write_text(
            "export const greet = name => `Hello ${name}`;\n"
        )

        # Exact visible output and action shape from /tmp/superpowers-mode-evals/
        # task1-final-full-a409482/claude/claude-fable-5/explicit-skill/
        # 20260721T082625Z-85911-31690/{assistant.txt,transcript.jsonl}
        claude_events = [
            claude_init(),
            claude_event(
                "Mode: lean — Explicit user instruction selecting lean for a small, "
                "exploratory naming discussion with no file changes.\n\n"
                "The brainstorming skill was explicitly requested, so it runs under "
                "this mode. Invoking it now."
            ),
            claude_tool_event(
                "Skill",
                {
                    "skill": "superpowers:brainstorming",
                    "args": "Explore two possible names for the greeting function; "
                    "no file changes.",
                },
                tool_id="brainstorming",
            ),
            claude_tool_result("brainstorming"),
            claude_event(
                "Announcing: the brainstorming skill is active. First step is "
                "read-only project context — let me find the greeting function."
            ),
            claude_tool_event(
                "Bash",
                {
                    "command": f'ls -la {self.project} && grep -rn -i "greet" '
                    f'{self.project} --include="*" -l',
                    "description": "List project files and find greeting references",
                },
                tool_id="shell-inspection",
            ),
            claude_tool_result("shell-inspection"),
            *claude_read_lifecycle(self.project, "src/greeting.js", "greeting"),
            claude_event(
                "The project has one file, `src/greeting.js:1`, containing "
                "`export const greet = name => `Hello ${name}`;`. You asked for two "
                "name options, so here they are with trade-offs — no files touched.\n\n"
                "**Option 1: `greet` (keep the current name)** — A verb, which "
                "matches convention for functions that perform an action and return "
                "a result. It's short, already exported, and renaming would touch "
                "any consumers for no behavioral gain. Slight downside: it doesn't "
                "hint at what the greeting contains or that it returns a string "
                "rather than printing.\n\n"
                "**Option 2: `greetByName`** — More descriptive: it signals the "
                "function takes a name and builds a personalized greeting, which "
                "reads well at call sites like `greetByName(\"Ada\")`. Downside: "
                "it's longer, and in a module already called `greeting.js` the extra "
                "specificity is mostly redundant — the file context already tells "
                "you what `greet` does.\n\n"
                "**My recommendation is Option 1, `greet`.** In a module named "
                "`greeting.js` with a single-argument signature, the short verb is "
                "unambiguous, idiomatic, and avoids a rename with no functional "
                "benefit.\n\n"
                "One question to converge: do you want to keep `greet`, or should "
                "we go with `greetByName` (or another direction, like a noun-returning "
                "style such as `makeGreeting`)? Per the brainstorming flow I'll "
                "treat your pick as the design decision — and since you said not to "
                "change files yet, nothing will be modified until you say so."
            ),
            {"type": "result", "subtype": "success", "result": "done"},
        ]

        # Exact visible output and post-declaration action shapes from the latest
        # Codex run at /tmp/superpowers-mode-evals/task1-final-full-a409482/codex/
        # gpt-5.6-sol/explicit-skill/20260721T083216Z-95613-27695/.
        codex_events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Loading workflow-selection sources before task analysis.",
                item_id="intro",
            ),
            codex_event(
                "Mode: lean — you explicitly requested lean mode for a read-only, "
                "reversible naming exploration.",
                item_id="declaration",
            ),
            codex_event(
                "I’m now applying the brainstorming workflow’s read-only context "
                "check so the two names fit the project’s existing naming style. "
                "No files will be changed.",
                item_id="inspection-intro",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc 'git log -5 --oneline'", "git-log"
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"rg --files -g '!node_modules' -g '!vendor' "
                "| sed -n '1,160p'\"",
                "rg-pipeline",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc 'git status --short'", "git-status"
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,240p' src/greeting.js\"",
                "greeting",
            ),
            codex_event(
                "Two options:\n\n"
                "1. `formatGreeting` — recommended. Clearly signals a pure function "
                "that returns a formatted string without displaying or sending it.\n"
                "2. `greet` — concise and friendly, but could imply performing an "
                "action rather than returning text.\n\n"
                "Given the current implementation, I’d choose `formatGreeting`. "
                "Which name do you prefer? No files changed.",
                item_id="options",
            ),
            {"type": "turn.completed", "usage": {}},
        ]

        for backend, events in (("claude", claude_events), ("codex", codex_events)):
            with self.subTest(backend=backend):
                result = self.run_validator(backend, "explicit-skill", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_exact_skill_tool_use_is_affirmative_evidence(self) -> None:
        options = claude_event(
            "Mode: lean — explicit read-only naming exploration.\n"
            "Option 1: `greet` — keep the action-oriented name.\n"
            "Option 2: `greeting` — emphasize the returned value."
        )
        exact = [
            claude_init(),
            options,
            claude_tool_event(
                "Skill",
                {"skill": "superpowers:brainstorming"},
                tool_id="brainstorming",
            ),
            claude_tool_result("brainstorming"),
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "explicit-skill", exact)
        self.assertEqual(result.returncode, 0, result.stderr)

        failed_result = claude_tool_result("brainstorming")
        failed_result["tool_use_result"] = {"success": False}
        invalid_results = (
            ("missing", []),
            ("error", [claude_tool_result("brainstorming", is_error=True)]),
            ("failed", [failed_result]),
            ("mismatched", [claude_tool_result("different")]),
        )
        for label, result_events in invalid_results:
            with self.subTest(result=label):
                invalid_lifecycle = [
                    claude_init(),
                    options,
                    exact[2],
                    *result_events,
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude", "explicit-skill", invalid_lifecycle
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("affirmative brainstorming", result.stderr)

        for skill in ("brainstorming", "superpowers:brainstorming-extra"):
            with self.subTest(skill=skill):
                malformed = [
                    claude_init(),
                    options,
                    claude_tool_event(
                        "Skill", {"skill": skill}, tool_id="brainstorming"
                    ),
                    claude_tool_result("brainstorming"),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "explicit-skill", malformed)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("explicit-skill action", result.stderr)

        negated = [
            *exact[:-1],
            claude_event("I am not using the brainstorming skill after all."),
            exact[-1],
        ]
        result = self.run_validator("claude", "explicit-skill", negated)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("affirmative brainstorming", result.stderr)

    def test_claude_failed_skill_attempt_blocks_visible_prose_fallback(self) -> None:
        visible = claude_event(
            "Mode: lean — explicit read-only naming exploration.\n"
            "I am using the brainstorming skill.\n"
            "Option 1: `greet`\nOption 2: `greeting`"
        )
        invocation = claude_tool_event(
            "Skill",
            {"skill": "superpowers:brainstorming"},
            tool_id="brainstorming",
        )
        malformed_success = claude_tool_result("brainstorming")
        malformed_success["tool_use_result"] = {"success": "false"}
        failures = (
            ("missing result", []),
            ("error result", [claude_tool_result("brainstorming", is_error=True)]),
            ("malformed success metadata", [malformed_success]),
        )
        for label, result_events in failures:
            with self.subTest(label=label):
                events = [
                    claude_init(),
                    visible,
                    invocation,
                    *result_events,
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("affirmative brainstorming", result.stderr)

        claude_no_skill = [
            claude_init(),
            visible,
            {"type": "result", "subtype": "success", "result": "done"},
        ]
        result = self.run_validator("claude", "explicit-skill", claude_no_skill)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("affirmative brainstorming", result.stderr)

        codex_visible_fallback = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit read-only naming exploration.\n"
                "I am using the brainstorming skill.\n"
                "Option 1: `greet`\nOption 2: `greeting`"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator(
            "codex", "explicit-skill", codex_visible_fallback
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_skill_rejects_mutation_and_unknown_actions(self) -> None:
        declaration = claude_event(
            "Mode: lean — explicit read-only naming exploration.\n"
            "I am using the brainstorming skill.\n"
            "Option 1: `greet`\nOption 2: `greeting`"
        )
        claude_mutations = (
            ("Write", {"file_path": str(self.project / "new.js"), "content": "x"}),
            (
                "Edit",
                {
                    "file_path": str(self.project / "src/schema.js"),
                    "old_string": "amount",
                    "new_string": "amountCents",
                },
            ),
            (
                "Bash",
                {"command": "python3 -c 'open(\"new.js\", \"w\").write(\"x\")'"},
            ),
            ("OpaqueTool", {"path": str(self.project)}),
        )
        for index, (name, tool_input) in enumerate(claude_mutations):
            with self.subTest(backend="claude", action=name):
                tool_id = f"mutation-{index}"
                events = [
                    claude_init(),
                    declaration,
                    claude_tool_event(name, tool_input, tool_id=tool_id),
                    claude_tool_result(tool_id),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("explicit-skill action", result.stderr)

        for label, inspection in (
            ("Read", claude_read_lifecycle(self.project, "src/schema.js", "read")),
            (
                "closed Bash",
                [
                    claude_tool_event(
                        "Bash",
                        {
                            "command": f"ls -la {self.project} && git -C "
                            f"{self.project} log --oneline -5"
                        },
                        tool_id="bash-read",
                    ),
                    claude_tool_result("bash-read"),
                ],
            ),
        ):
            with self.subTest(backend="claude", read_only=label):
                read_only_claude = [
                    claude_init(),
                    declaration,
                    claude_tool_event(
                        "Skill",
                        {"skill": "superpowers:brainstorming"},
                        tool_id="brainstorming",
                    ),
                    claude_tool_result("brainstorming"),
                    *inspection,
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator(
                    "claude", "explicit-skill", read_only_claude
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        codex_declaration = codex_event(
            "Mode: lean — explicit read-only naming exploration.\n"
            "I am using the brainstorming skill.\n"
            "Option 1: `greet`\nOption 2: `greeting`",
            item_id="declaration",
        )
        codex_actions = (
            codex_command_lifecycle(
                "python3 -c 'open(\"new.js\", \"w\").write(\"x\")'",
                "mutation",
            ),
            [
                codex_event(
                    "opaque",
                    item_type="mcp_tool_call",
                    event_type="item.started",
                    item_id="unknown",
                ),
                codex_event(
                    "opaque", item_type="mcp_tool_call", item_id="unknown"
                ),
            ],
        )
        for index, action in enumerate(codex_actions):
            with self.subTest(backend="codex", action=index):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_declaration,
                    *action,
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("explicit-skill action", result.stderr)

        for label, command in (
            ("cat", "cat src/schema.js"),
            (
                "closed rg pipeline",
                "/bin/zsh -lc \"rg --files -g '!node_modules' -g '!vendor' "
                "| sed -n '1,160p'\"",
            ),
        ):
            with self.subTest(backend="codex", read_only=label):
                read_only_codex = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_declaration,
                    *codex_command_lifecycle(command, "read"),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator(
                    "codex", "explicit-skill", read_only_codex
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_skill_rejects_unsafe_shell_composition_segments(self) -> None:
        visible = (
            "Mode: lean — explicit read-only naming exploration.\n"
            "I am using the brainstorming skill.\n"
            "Option 1: `greet`\nOption 2: `formatGreeting`"
        )
        unsafe_commands = (
            f"ls -la {self.project} && touch {self.project / 'new.js'}",
            "rg --files | sed -n '1,20p' > inventory.txt",
            "rg --files | python3 -c 'print(1)'",
            "git status --short && git restore src/schema.js",
            "ls $(touch new.js)",
            "ls -la . && opaque-reader .",
        )
        for backend in ("claude", "codex"):
            for index, command in enumerate(unsafe_commands):
                with self.subTest(backend=backend, command=command):
                    if backend == "claude":
                        events = [
                            claude_init(),
                            claude_event(visible),
                            claude_tool_event(
                                "Skill",
                                {"skill": "superpowers:brainstorming"},
                                tool_id="brainstorming",
                            ),
                            claude_tool_result("brainstorming"),
                            claude_tool_event(
                                "Bash", {"command": command}, tool_id=f"unsafe-{index}"
                            ),
                            claude_tool_result(f"unsafe-{index}"),
                            {"type": "result", "subtype": "success", "result": "done"},
                        ]
                    else:
                        events = [
                            {"type": "thread.started", "thread_id": "thread"},
                            codex_event(visible, item_id="declaration"),
                            *codex_command_lifecycle(command, f"unsafe-{index}"),
                            {"type": "turn.completed", "usage": {}},
                        ]
                    result = self.run_validator(backend, "explicit-skill", events)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("explicit-skill action", result.stderr)

    def test_explicit_skill_uses_final_invocation_polarity(self) -> None:
        negations = (
            "I am not using the brainstorming skill after all.",
            "I am not invoking it after all.",
            "We are no longer using that skill.",
            "I won't use it after all.",
            "I didn't invoke that skill.",
        )
        for negation in negations:
            with self.subTest(negation=negation):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: lean — explicit override.\n"
                        "I am using the brainstorming skill.\n"
                        "Options are welcomeUser and greetUser.\n"
                        f"{negation}"
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("affirmative brainstorming", result.stderr)

    def test_explicit_skill_parses_candidate_polarity_per_clause(self) -> None:
        positives = (
            "Options are welcomeUser and greetUser; avoid currentName.",
            "Candidates are welcomeUser and greetUser; ~~Option: currentName~~.",
            "Options are welcomeUser, greetUser, and currentName (rejected).",
        )
        for candidates in positives:
            with self.subTest(candidates=candidates):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: lean — explicit override.\n"
                        "I am using the brainstorming skill.\n"
                        f"{candidates}"
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertEqual(result.returncode, 0, result.stderr)

        negative = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — explicit override.\n"
                "I am using the brainstorming skill.\n"
                "Option: welcomeUser; not recommended candidate: currentName."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "explicit-skill", negative)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("two distinct positive", result.stderr)

    def test_explicit_skill_rejects_current_existing_or_struck_candidate_units(self) -> None:
        candidate_units = (
            "1. Option: currentName (current)\n2. Option: welcomeUser",
            "1. Option: currentName (existing identifier)\n2. Option: welcomeUser",
            "1. Option: currentName (struck)\n2. Option: welcomeUser",
            "1. Option: currentName (strikeout)\n2. Option: welcomeUser",
            "Rejected options are currentName and greetUser.\n1. Option: welcomeUser",
            "Existing candidates are currentName and greetUser.\n1. Option: welcomeUser",
            "~~Options are currentName and greetUser~~.\n1. Option: welcomeUser",
            "Options are welcomeUser, currentName (rejected), and existingName (existing).",
        )
        for candidate_units_text in candidate_units:
            with self.subTest(candidate_units=candidate_units_text):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    codex_event(
                        "Mode: lean — explicit override.\n"
                        "I am using the brainstorming skill.\n"
                        f"{candidate_units_text}"
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "explicit-skill", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("two distinct positive", result.stderr)

    def test_claude_requires_exact_inline_checkout_plugin_identity(self) -> None:
        for init in (
            claude_init(path="/upstream/superpowers"),
            claude_init(source="superpowers@official"),
            claude_init(version="wrong-version"),
        ):
            with self.subTest(init=init):
                events = [
                    init,
                    claude_event("Mode: lean — typo correction.\nVerification passed."),
                    {"type": "result", "subtype": "success", "result": "done"},
                ]
                result = self.run_validator("claude", "lean", events, plugin_identity=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("inline checkout plugin", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
