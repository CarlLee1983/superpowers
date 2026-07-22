import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "report-upstream-changes.py"
HEADINGS = (
    "Skill behavior",
    "Harness and plugin integration",
    "Hooks and bootstrap",
    "Tests and evaluations",
    "Documentation and release metadata",
    "Other",
)


class UpstreamChangeReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Upstream Report Test")
        self.git("config", "user.email", "report@example.invalid")

        self.write("skills/existing/SKILL.md", "base skill\n")
        self.write(".codex-plugin/plugin.json", '{"version":"6.1.1"}\n')
        self.write("hooks/session-start", "base hook\n")
        self.write("tests/old-name.sh", "#!/bin/sh\nexit 0\n")
        self.write("README.md", "base readme\n")
        self.write("source.txt", "base other\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.base_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("tag", "-a", "v6.1.1", "-m", "v6.1.1")

        self.write("skills/new-skill/SKILL.md", "new skill\n")
        self.write(".codex-plugin/plugin.json", '{"version":"6.1.2"}\n')
        (self.root / "hooks/session-start").unlink()
        self.git("mv", "tests/old-name.sh", "tests/new-name.sh")
        self.write("README.md", "updated readme\n")
        self.write("misc/new-file.txt", "unmatched\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "target")
        self.target_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("tag", "-a", "v6.1.2", "-m", "v6.1.2")

        metadata = {
            "repository": "https://github.com/obra/superpowers.git",
            "tag": "v6.1.1",
            "commit": self.base_commit,
        }
        self.write(".adaptive-base.json", json.dumps(metadata, indent=2) + "\n")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            text=True,
            capture_output=True,
        )

    def write(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run_report(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                *arguments,
            ],
            text=True,
            capture_output=True,
        )

    @staticmethod
    def section(report: str, heading: str) -> str:
        marker = f"## {heading}\n"
        start = report.index(marker) + len(marker)
        end = report.find("\n## ", start)
        return report[start:] if end == -1 else report[start:end]

    def test_groups_each_change_exactly_once(self):
        result = self.run_report("--target-ref", "v6.1.2")

        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            "Skill behavior": "A\tskills/new-skill/SKILL.md",
            "Harness and plugin integration": "M\t.codex-plugin/plugin.json",
            "Hooks and bootstrap": "D\thooks/session-start",
            "Tests and evaluations": "R100\ttests/old-name.sh\ttests/new-name.sh",
            "Documentation and release metadata": "M\tREADME.md",
            "Other": "A\tmisc/new-file.txt",
        }
        for heading, change in expected.items():
            with self.subTest(heading=heading):
                self.assertIn(f"`{change}`", self.section(result.stdout, heading))
                self.assertEqual(result.stdout.count(f"`{change}`"), 1)

    def test_defaults_base_ref_from_metadata_and_reports_resolved_commits(self):
        result = self.run_report("--target-ref", "v6.1.2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Base: `v6.1.1` (`{self.base_commit}`)", result.stdout)
        self.assertIn(f"Target: `v6.1.2` (`{self.target_commit}`)", result.stdout)

    def test_includes_all_six_groups_even_when_empty(self):
        result = self.run_report("--target-ref", "v6.1.1")

        self.assertEqual(result.returncode, 0, result.stderr)
        for heading in HEADINGS:
            with self.subTest(heading=heading):
                self.assertIn("_No changes._", self.section(result.stdout, heading))

    def test_rejects_unknown_revision(self):
        result = self.run_report("--target-ref", "v9.9.9")

        self.assertEqual(result.returncode, 1)
        self.assertIn("error: cannot resolve revision v9.9.9", result.stderr)


if __name__ == "__main__":
    unittest.main()
