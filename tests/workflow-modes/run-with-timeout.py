#!/usr/bin/env python3
"""Run one command in a new session and terminate its whole process group on timeout."""

from __future__ import annotations

import os
import signal
import subprocess
import sys


def signal_group(pid: int, signal_number: signal.Signals) -> None:
    try:
        os.killpg(pid, signal_number)
    except ProcessLookupError:
        pass


def main(argv: list[str]) -> int:
    if len(argv) < 6:
        print(
            "usage: run-with-timeout.py <seconds> <term-grace-seconds> "
            "<stdout> <stderr> <command> [args...]",
            file=sys.stderr,
        )
        return 2
    timeout = float(argv[1])
    grace = float(argv[2])
    stdout_name, stderr_name = argv[3:5]
    command = argv[5:]
    if timeout <= 0 or grace < 0:
        print("timeout must be positive and grace must be non-negative", file=sys.stderr)
        return 2

    with open(stdout_name, "wb") as stdout_file, open(stderr_name, "wb") as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stderr_file.write(f"command timed out after {timeout:g} seconds\n".encode())
            stderr_file.flush()
            signal_group(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            signal_group(process.pid, signal.SIGKILL)
            try:
                process.wait(timeout=max(grace, 0.1))
            except subprocess.TimeoutExpired:
                stderr_file.write(b"process leader did not exit after SIGKILL\n")
            return 124


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
