import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "validate-adaptive-base.py"
VERSION_FILES = (
    ("package.json", "version"),
    (".claude-plugin/plugin.json", "version"),
    (".cursor-plugin/plugin.json", "version"),
    (".codex-plugin/plugin.json", "version"),
    (".kimi-plugin/plugin.json", "version"),
    (".claude-plugin/marketplace.json", "plugins.0.version"),
    ("gemini-extension.json", "version"),
)


class AdaptiveBaseValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Adaptive Test")
        self.git("config", "user.email", "adaptive@example.invalid")

        (self.root / "upstream.txt").write_text("upstream base\n", encoding="utf-8")
        self.git("add", "upstream.txt")
        self.git("commit", "-q", "-m", "upstream base")
        self.base_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("tag", "-a", "v6.1.1", "-m", "upstream v6.1.1")

        self.write_base_metadata()
        self.write_versions("6.1.1-adaptive.3")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "adaptive release")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            text=True,
            capture_output=True,
        )

    def write_json(self, relative_path: str, document: object) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def write_base_metadata(self, **overrides: str) -> None:
        document = {
            "repository": "https://github.com/obra/superpowers.git",
            "tag": "v6.1.1",
            "commit": self.base_commit,
        }
        document.update(overrides)
        self.write_json(".adaptive-base.json", document)

    def write_versions(self, version: str) -> None:
        mappings = []
        for relative_path, field in VERSION_FILES:
            mappings.append({"path": relative_path, "field": field})
            if field == "version":
                self.write_json(relative_path, {"version": version})
            else:
                self.write_json(relative_path, {"plugins": [{"version": version}]})
        self.write_json(".version-bump.json", {"files": mappings, "audit": {"exclude": []}})

    def run_validator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *arguments],
            text=True,
            capture_output=True,
        )

    def test_accepts_matching_base_and_versions(self):
        result = self.run_validator()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"Adaptive 6.1.1-adaptive.3 is based on v6.1.1 ({self.base_commit})",
            result.stdout,
        )

    def test_rejects_missing_base_metadata(self):
        (self.root / ".adaptive-base.json").unlink()

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn("error: .adaptive-base.json is missing", result.stderr)

    def test_rejects_adaptive_version_not_matching_upstream_tag(self):
        self.write_versions("6.1.2-adaptive.1")

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match upstream tag v6.1.1", result.stderr)

    def test_rejects_manifest_version_drift(self):
        self.write_json("gemini-extension.json", {"version": "6.1.1-adaptive.2"})

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "gemini-extension.json (version) is 6.1.1-adaptive.2; expected 6.1.1-adaptive.3",
            result.stderr,
        )

    def test_rejects_tag_commit_mismatch(self):
        self.write_base_metadata(commit="0" * 40)

        result = self.run_validator()

        self.assertEqual(result.returncode, 1)
        self.assertIn("v6.1.1 resolves to", result.stderr)
        self.assertIn("metadata records", result.stderr)

    def test_release_tag_must_resolve_to_head(self):
        self.git("tag", "-a", "v6.1.1-adaptive.3", self.base_commit, "-m", "wrong release")

        result = self.run_validator("--release-tag", "v6.1.1-adaptive.3")

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not resolve to HEAD", result.stderr)

    def test_accepts_release_tag_at_head(self):
        self.git("tag", "-a", "v6.1.1-adaptive.3", "-m", "adaptive release")

        result = self.run_validator("--release-tag", "v6.1.1-adaptive.3")

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
