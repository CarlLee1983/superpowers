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


def codex_event(text: str, *, item_type: str = "agent_message") -> dict:
    item = {"id": "item_1", "type": item_type}
    if item_type == "agent_message":
        item["text"] = text
    else:
        item["command"] = text
    return {"type": "item.completed", "item": item}


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
    ) -> subprocess.CompletedProcess[str]:
        log = self.write_jsonl(f"{backend}-{case}.jsonl", events)
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                backend,
                expected_model,
                case,
                str(log),
            ],
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
            claude_event("Mode: lean", block_type="tool_use"),
            claude_event("Mode: lean — localized typo correction.\nVerified README content."),
            {"type": "result", "subtype": "success", "result": "duplicate result text"},
        ]
        result = self.run_validator("claude", "lean", events)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: lean", result.stdout)

    def test_codex_counts_only_agent_messages(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread"},
            codex_event("printf 'Mode: strict'", item_type="command_execution"),
            codex_event("Mode: standard — bounded CLI change.\nTests passed."),
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
            codex_event("Mode: lean — first."),
            codex_event("Mode: lean — repeated."),
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
                "I am promoting the workflow because this is a production billing API."
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
                "rename changes its public response shape."
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
        self.assertIn("assistant-visible brainstorming", failing.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
