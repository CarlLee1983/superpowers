import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATE_WORKFLOW = ROOT / ".github" / "workflows" / "adaptive-validate.yml"
WATCH_WORKFLOW = ROOT / ".github" / "workflows" / "adaptive-upstream-watch.yml"


class AdaptiveWorkflowTests(unittest.TestCase):
    def test_validation_workflow_runs_repository_release_gate(self):
        self.assertTrue(VALIDATE_WORKFLOW.is_file())
        text = VALIDATE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("scripts/validate-adaptive-release.sh", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("@openai/codex", text)

    def test_upstream_watch_is_read_only_and_reports_grouped_diff(self):
        self.assertTrue(WATCH_WORKFLOW.is_file())
        text = WATCH_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("contents: read", text)
        self.assertIn("scripts/report-upstream-changes.py", text)
        self.assertIn("$GITHUB_STEP_SUMMARY", text)
        self.assertIsNone(
            re.search(r"\b(git push|gh pr|gh issue|gh release)\b", text),
            "upstream watcher must not publish or mutate repository state",
        )


if __name__ == "__main__":
    unittest.main()
