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
    ) -> subprocess.CompletedProcess[str]:
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
            codex_event("Mode: standard — bounded CLI change.\nTests passed."),
            *codex_command_lifecycle("printf 'Mode: strict'", "item_2"),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertEqual(result.returncode, 0, result.stderr)

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
        self.assertIn("exactly one assistant-visible", result.stderr)

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

    def test_escalation_codex_accepts_wrapped_project_glob_inspection(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: standard — bounded rename pending repository inspection.",
                item_id="declaration",
            ),
            *codex_command_lifecycle(
                "/bin/zsh -lc \"sed -n '1,240p' src/*\"",
                "glob-inspection",
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
        preamble, declaration, promotion, explanation_and_pause = LATEST_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(preamble, item_id="preamble"),
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
        preamble, declaration, promotion_and_pause = LATEST_19A_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(preamble, item_id="preamble"),
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
        preamble, declaration, promotion, pause = LATEST_F9A_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(preamble, item_id="preamble"),
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
        preamble, declaration, promotion_and_pause = LATEST_F1B_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(preamble, item_id="preamble"),
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
        preamble, declaration, promotion, pause = LATEST_BE5_CODEX_OUTPUTS
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(preamble, item_id="preamble"),
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
                "Warning: authentication is security-sensitive; I will remain lean as requested."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_accepts_authoritative_explicit_lean_wording(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — The user explicitly requested lean mode.\n"
                "Authentication is normally a strict-risk area, but your explicit "
                "lean override is authoritative here; I’ll keep the change tightly scoped."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_override_does_not_require_a_redundant_lean_continuity_sentence(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: lean — the user explicitly requested lean mode for this localized "
                "authentication fix, despite authentication normally being a strict-risk trigger.\n"
                "Verification: npm test passes."
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "override", events)
        self.assertEqual(result.returncode, 0, result.stderr)

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
            *codex_command_lifecycle(
                "sed -n '1,200p' "
                "/expected/checkout/skills/selecting-workflow-mode/SKILL.md",
                "item_1",
            ),
            codex_event(
                "Mode: standard — bounded CLI change.\nTests passed.",
                item_id="message",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_does_not_trust_reused_item_ids_before_declaration(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            *codex_command_lifecycle(
                "sed -n '1,200p' "
                "/expected/checkout/skills/selecting-workflow-mode/SKILL.md",
                "item_1",
            ),
            codex_event(
                "git status --short",
                item_type="command_execution",
                event_type="item.started",
                item_id="item_1",
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
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        matrix = (
            "/expected/checkout/skills/selecting-workflow-mode/"
            "references/risk-matrix.md"
        )
        for command in (
            f"cat {selector} {matrix}",
            f"sed -n '1,260p' {selector} {matrix}",
            f"/bin/zsh -lc \"sed -n '1,260p' {matrix}\"",
        ):
            with self.subTest(command=command):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    *codex_command_lifecycle(command, "bootstrap"),
                    codex_event(
                        "Mode: standard — bounded change.\nTests passed.",
                        item_id="message",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_rejects_invalid_item_lifecycle(self) -> None:
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        bootstrap = f"cat {selector}"
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
                    item_id="b",
                ),
            ],
        )
        for lifecycle in mutations:
            with self.subTest(lifecycle=lifecycle):
                events = [
                    {"type": "thread.started", "thread_id": "thread"},
                    *lifecycle,
                    codex_event(
                        "Mode: standard — bounded change.\nTests passed.",
                        item_id="message",
                    ),
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
                    codex_event(
                        "Mode: standard — bounded change.\nTests passed.",
                        item_id="message",
                    ),
                    {"type": "turn.completed", "usage": {}},
                ]
                result = self.run_validator("codex", "standard", events)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("item lifecycle changed immutable payload", result.stderr)

    def test_codex_accepts_consistent_updated_item_lifecycle(self) -> None:
        selector = "/expected/checkout/skills/selecting-workflow-mode/SKILL.md"
        bootstrap = f"cat {selector}"
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
            ),
            codex_event(
                "Mode: standard — bounded change.\nTests passed.",
                item_id="message",
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "standard", events)
        self.assertEqual(result.returncode, 0, result.stderr)

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
