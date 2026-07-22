import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION_TEST = ROOT / "tests" / "workflow-modes" / "test-docs-and-version.sh"
STATIC_RUNNER = ROOT / "tests" / "workflow-modes" / "run-static-tests.sh"


class RepositoryContractTests(unittest.TestCase):
    def test_workflow_version_test_derives_the_manifest_version(self):
        text = VERSION_TEST.read_text(encoding="utf-8")

        self.assertIsNone(re.search(r'TARGET_VERSION="[0-9].*-adaptive', text))
        self.assertIn(
            "TARGET_VERSION=\"$(jq -r '.version' \"$ROOT/.codex-plugin/plugin.json\")\"",
            text,
        )

    def test_static_runner_executes_state_machine_suite_once(self):
        text = STATIC_RUNNER.read_text(encoding="utf-8")
        command = "python3 -m unittest tests/workflow-modes/test_state_machine.py -v"

        self.assertEqual(text.count(command), 1)


if __name__ == "__main__":
    unittest.main()
