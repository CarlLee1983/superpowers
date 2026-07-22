import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tests" / "workflow-modes" / "assert-state-machine.py"


def load_validator():
    if not VALIDATOR_PATH.is_file():
        raise AssertionError(f"state-machine validator is missing: {VALIDATOR_PATH}")
    spec = importlib.util.spec_from_file_location("workflow_state_machine", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load state-machine validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkflowStateMachineTests(unittest.TestCase):
    def validate(self, events: list[dict[str, object]]) -> list[str]:
        return load_validator().validate_trace(events)

    def assert_valid(self, events: list[dict[str, object]]) -> None:
        self.assertEqual(self.validate(events), [])

    def assert_invalid(self, events: list[dict[str, object]], expected: str) -> None:
        errors = self.validate(events)
        self.assertTrue(
            any(expected in error for error in errors),
            f"expected {expected!r} in {errors!r}",
        )

    def test_accepts_lean_verified_completion(self):
        self.assert_valid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "lean", "override": "none"},
                {"event": "readiness", "mode": "lean"},
                {"event": "mutation"},
                {"event": "verification", "fresh": True, "status": 0},
                {"event": "completion_claim"},
            ]
        )

    def test_accepts_evidence_backed_automatic_promotion(self):
        self.assert_valid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "standard", "override": "none"},
                {"event": "inspection", "evidence": "schema feeds billing API"},
                {"event": "promotion", "mode": "strict", "evidence": "payment schema"},
                {"event": "readiness", "mode": "strict"},
                {"event": "mutation"},
                {"event": "verification", "fresh": True, "status": 0},
                {"event": "completion_claim"},
            ]
        )

    def test_accepts_explicit_override_warning_without_promotion(self):
        self.assert_valid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "lean", "override": "lean"},
                {"event": "warning", "evidence": "authentication boundary"},
                {"event": "readiness", "mode": "lean"},
                {"event": "mutation"},
                {"event": "verification", "fresh": True, "status": 0},
                {"event": "completion_claim"},
            ]
        )

    def test_rejects_duplicate_declaration(self):
        self.assert_invalid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "lean", "override": "none"},
                {"event": "mode_declared", "mode": "standard", "override": "none"},
            ],
            "exactly one mode declaration",
        )

    def test_rejects_mutation_before_declaration(self):
        self.assert_invalid(
            [{"event": "task_start"}, {"event": "mutation"}],
            "mutation occurred before mode declaration",
        )

    def test_rejects_mutation_before_readiness(self):
        self.assert_invalid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "standard", "override": "none"},
                {"event": "mutation"},
            ],
            "mutation occurred before readiness",
        )

    def test_rejects_automatic_demotion(self):
        self.assert_invalid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "standard", "override": "none"},
                {"event": "inspection", "evidence": "lower risk than expected"},
                {"event": "promotion", "mode": "lean", "evidence": "small diff"},
            ],
            "automatic mode change must promote to strict",
        )

    def test_rejects_override_promotion(self):
        self.assert_invalid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "lean", "override": "lean"},
                {"event": "inspection", "evidence": "authentication boundary"},
                {"event": "promotion", "mode": "strict", "evidence": "auth change"},
            ],
            "explicit non-strict override must warn instead of promoting",
        )

    def test_rejects_promotion_without_evidence(self):
        self.assert_invalid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "standard", "override": "none"},
                {"event": "promotion", "mode": "strict", "evidence": ""},
            ],
            "promotion requires prior inspection evidence",
        )

    def test_rejects_completion_without_fresh_successful_verification(self):
        for verification, label in (
            ({"event": "verification", "fresh": False, "status": 0}, "fresh"),
            ({"event": "verification", "fresh": True, "status": 1}, "successful"),
        ):
            with self.subTest(label=label):
                self.assert_invalid(
                    [
                        {"event": "task_start"},
                        {"event": "mode_declared", "mode": "lean", "override": "none"},
                        {"event": "readiness", "mode": "lean"},
                        {"event": "mutation"},
                        verification,
                        {"event": "completion_claim"},
                    ],
                    "completion claim requires fresh successful verification",
                )

    def test_rejects_verification_that_precedes_final_mutation(self):
        self.assert_invalid(
            [
                {"event": "task_start"},
                {"event": "mode_declared", "mode": "lean", "override": "none"},
                {"event": "readiness", "mode": "lean"},
                {"event": "verification", "fresh": True, "status": 0},
                {"event": "mutation"},
                {"event": "completion_claim"},
            ],
            "verification must follow the final mutation",
        )


if __name__ == "__main__":
    unittest.main()
