import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "validate-adaptive-release.sh"
COMMANDS = (
    "scripts/validate-adaptive-base.py",
    "tests/adaptive-maintenance/run-tests.sh",
    "tests/workflow-modes/run-static-tests.sh",
    "tests/codex/test-marketplace-manifest.sh",
    "tests/codex/test-package-codex-plugin.sh",
    "scripts/smoke-codex-install.sh",
    "tests/hooks/test-session-start.sh",
)


class AdaptiveReleaseRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.fixture = Path(self.temporary_directory.name)
        self.log = self.fixture / "calls.log"
        for relative_path in COMMANDS:
            path = self.fixture / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s\\t%s\\n' \"$(basename \"$0\")\" \"$*\" >> \"$ADAPTIVE_RUNNER_LOG\"\n"
                "if [[ \"${ADAPTIVE_FAIL_COMMAND:-}\" == \"$(basename \"$0\")\" ]]; then exit 23; fi\n",
                encoding="utf-8",
            )
            path.chmod(0o755)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_runner(self, *arguments: str, fail_command: str = "") -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "ADAPTIVE_TEST_ROOT": str(self.fixture),
                "ADAPTIVE_RUNNER_LOG": str(self.log),
                "ADAPTIVE_FAIL_COMMAND": fail_command,
            }
        )
        return subprocess.run(
            ["bash", str(RUNNER), *arguments],
            text=True,
            capture_output=True,
            env=environment,
        )

    def logged_calls(self) -> list[str]:
        if not self.log.is_file():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_runs_every_validation_layer_in_order(self):
        result = self.run_runner()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [line.split("\t", 1)[0] for line in self.logged_calls()],
            [Path(path).name for path in COMMANDS],
        )

    def test_passes_release_tag_only_to_base_validator(self):
        result = self.run_runner("--release-tag", "v6.1.1-adaptive.3")

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.logged_calls()
        self.assertEqual(
            calls[0],
            "validate-adaptive-base.py\t--release-tag v6.1.1-adaptive.3",
        )
        self.assertTrue(all(line.endswith("\t") for line in calls[1:]))

    def test_stops_at_first_failure_and_preserves_status(self):
        result = self.run_runner(fail_command="run-static-tests.sh")

        self.assertEqual(result.returncode, 23)
        self.assertEqual(
            [line.split("\t", 1)[0] for line in self.logged_calls()],
            [
                "validate-adaptive-base.py",
                "run-tests.sh",
                "run-static-tests.sh",
            ],
        )

    def test_rejects_unknown_arguments(self):
        result = self.run_runner("--publish")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.logged_calls(), [])


if __name__ == "__main__":
    unittest.main()
