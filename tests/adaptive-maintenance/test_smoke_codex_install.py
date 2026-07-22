import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "scripts" / "smoke-codex-install.sh"


class CodexInstallSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.fixture = Path(self.temporary_directory.name)
        self.log = self.fixture / "codex-calls.jsonl"
        self.codex = self.fixture / "codex-stub"
        self.codex.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import shutil
                import sys
                from pathlib import Path

                source = Path(os.environ["STUB_SOURCE_ROOT"])
                home = Path(os.environ["CODEX_HOME"])
                log = Path(os.environ["STUB_CODEX_LOG"])
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"home": str(home), "args": sys.argv[1:]}) + "\\n")

                args = sys.argv[1:]
                if args[:2] == ["plugin", "add"]:
                    version = json.loads((source / ".codex-plugin/plugin.json").read_text())["version"]
                    cache = home / "plugins/cache/superpowers-dev/superpowers" / version
                    for relative in (
                        ".codex-plugin/plugin.json",
                        "skills/selecting-workflow-mode/SKILL.md",
                        "skills/selecting-workflow-mode/references/risk-matrix.md",
                        "skills/using-superpowers/SKILL.md",
                    ):
                        destination = cache / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source / relative, destination)
                    print(json.dumps({"installed": "superpowers@superpowers-dev"}))
                elif args[:2] == ["plugin", "list"]:
                    version = json.loads((source / ".codex-plugin/plugin.json").read_text())["version"]
                    print(json.dumps({"installed": [{
                        "pluginId": "superpowers@superpowers-dev",
                        "enabled": True,
                        "version": version,
                        "marketplaceSource": {"source": str(source)},
                    }]}))
                elif args[:3] == ["plugin", "marketplace", "add"]:
                    print(json.dumps({"marketplace": "superpowers-dev"}))
                elif args and args[0] == "exec":
                    if os.environ.get("STUB_REQUIRE_AUTH") == "1":
                        auth = home / "auth.json"
                        if not auth.is_file() or auth.stat().st_mode & 0o077:
                            print("ephemeral home is missing private auth.json", file=sys.stderr)
                            raise SystemExit(17)
                    print(json.dumps({
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "Mode: lean — read-only smoke."},
                    }))
                else:
                    print(f"unexpected arguments: {args}", file=sys.stderr)
                    raise SystemExit(9)
                """
            ),
            encoding="utf-8",
        )
        self.codex.chmod(0o755)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_smoke(
        self, *arguments: str, require_auth: bool = False
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_BIN": str(self.codex),
                "STUB_SOURCE_ROOT": str(ROOT),
                "STUB_CODEX_LOG": str(self.log),
            }
        )
        if "--session" in arguments:
            auth_home = self.fixture / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text('{"fixture":"credential"}\n')
            (auth_home / "auth.json").chmod(0o600)
            environment["ADAPTIVE_CODEX_AUTH_HOME"] = str(auth_home)
        if require_auth:
            environment["STUB_REQUIRE_AUTH"] = "1"
        return subprocess.run(
            ["bash", str(SMOKE), *arguments],
            text=True,
            capture_output=True,
            env=environment,
        )

    def calls(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]

    def test_clean_install_verifies_plugin_without_starting_session(self):
        result = self.run_smoke()

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(
            [call["args"][:2] for call in calls],
            [["plugin", "marketplace"], ["plugin", "add"], ["plugin", "list"]],
        )
        self.assertEqual(len({call["home"] for call in calls}), 1)
        self.assertFalse(Path(str(calls[0]["home"])).exists())
        self.assertIn("Clean Codex install verified", result.stdout)

    def test_session_option_runs_one_ephemeral_lean_smoke(self):
        result = self.run_smoke("--session", "gpt-test-model")

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        exec_calls = [call["args"] for call in calls if call["args"][0] == "exec"]
        self.assertEqual(len(exec_calls), 1)
        self.assertIn("--ephemeral", exec_calls[0])
        self.assertIn("gpt-test-model", exec_calls[0])
        self.assertIn("Ephemeral Codex session verified", result.stdout)

    def test_session_uses_private_temporary_copy_of_existing_auth(self):
        result = self.run_smoke(
            "--session", "gpt-test-model", require_auth=True
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ephemeral Codex session verified", result.stdout)

    def test_rejects_unknown_arguments_before_calling_codex(self):
        result = self.run_smoke("--keep-home")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
