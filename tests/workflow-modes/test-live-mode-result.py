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


def claude_tool_event(name: str, tool_input: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": tool_input}],
        },
    }


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
) -> dict:
    item = {"id": item_id, "type": item_type}
    if item_type == "agent_message":
        item["text"] = text
    else:
        item["command"] = text
    return {"type": event_type, "item": item}


def codex_command_lifecycle(command: str, item_id: str) -> list[dict]:
    return [
        codex_event(
            command,
            item_type="command_execution",
            event_type="item.started",
            item_id=item_id,
        ),
        codex_event(command, item_type="command_execution", item_id=item_id),
    ]


class ValidatorTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

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

    def test_escalation_requires_strict_declaration_and_promotion_signal(self) -> None:
        base = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: strict — public payment API risk discovered.\n"
                "I am promoting the workflow because this is a production billing API. "
                "Should the compatibility alias remain during migration?"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        passing = self.run_validator("codex", "escalation", base)
        self.assertEqual(passing.returncode, 0, passing.stderr)

        missing_signal = [
            base[0],
            codex_event("Mode: strict — payment rename."),
            base[2],
        ]
        failing = self.run_validator("codex", "escalation", missing_signal)
        self.assertNotEqual(failing.returncode, 0)
        self.assertIn("promotion/escalation", failing.stderr)

    def test_escalation_accepts_an_explicit_discovered_public_shape_risk(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: strict — renaming an amount field can affect payment-domain "
                "compatibility across downstream consumers.\n"
                "The repository exposes this field through a public response, so the "
                "rename changes its public response shape. Should existing API clients "
                "retain the amount alias during migration?"
            ),
            {"type": "turn.completed", "usage": {}},
        ]
        result = self.run_validator("codex", "escalation", events)
        self.assertEqual(result.returncode, 0, result.stderr)

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
            "Mode: strict — migration design is complete. I approve this API design.",
            "Mode: strict — migration design is complete. We confirm API compatibility.",
            "Mode: strict — migration design is complete. I approve this API design?",
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
            "Can you confirm whether existing API clients must retain the alias?",
            "Could you approve this API design?",
            "Please approve the proposed payment migration design before implementation.",
            "Please confirm API compatibility before implementation.",
            "I need your approval before proceeding with the API migration.",
            "I need your decision before proceeding with the payment migration.",
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

    def test_escalation_requires_a_relevant_question_or_approval_request(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event(
                "Mode: strict — public payment API compatibility risk discovered.\n"
                "I am promoting the workflow because this changes production billing. Done."
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
