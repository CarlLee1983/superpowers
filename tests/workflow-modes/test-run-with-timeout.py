#!/usr/bin/env python3
"""Contract tests for bounded process-group termination."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run-with-timeout.py"


class TimeoutRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stdout = self.root / "stdout.log"
        self.stderr = self.root / "stderr.log"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_helper(
        self, timeout: str, grace: str, command: list[str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                timeout,
                grace,
                str(self.stdout),
                str(self.stderr),
                *command,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def process_is_running(self, pid: int) -> bool:
        status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
        return bool(status) and not status.startswith("Z")

    def test_propagates_nonzero_exit_status(self) -> None:
        result = self.run_helper(
            "2", "0.2", [sys.executable, "-c", "raise SystemExit(37)"]
        )
        self.assertEqual(result.returncode, 37)

    def test_accepts_command_without_arguments(self) -> None:
        result = self.run_helper("2", "0.2", ["true"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_timeout_terminates_descendant_process_group(self) -> None:
        pid_file = self.root / "child.pid"
        script = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); "
            "time.sleep(60)"
        )
        started = time.monotonic()
        result = self.run_helper(
            "0.2", "0.2", [sys.executable, "-c", script, str(pid_file)]
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 124)
        self.assertLess(elapsed, 2.0)
        self.assertIn("timed out", self.stderr.read_text())
        child_pid = int(pid_file.read_text())
        deadline = time.monotonic() + 2
        while self.process_is_running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(
            self.process_is_running(child_pid), f"descendant {child_pid} survived"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
