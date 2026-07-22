#!/usr/bin/env python3
"""Render a deterministic, grouped report for a tagged upstream diff."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


GROUPS = (
    ("Skill behavior", ("skills/",)),
    (
        "Harness and plugin integration",
        (
            ".codex-plugin/",
            ".claude-plugin/",
            ".cursor-plugin/",
            ".kimi-plugin/",
            ".opencode/",
            ".pi/",
            "gemini-extension.json",
        ),
    ),
    ("Hooks and bootstrap", ("hooks/",)),
    ("Tests and evaluations", ("tests/", "evals/")),
    (
        "Documentation and release metadata",
        (
            "docs/",
            "README.md",
            "RELEASE-NOTES.md",
            "CHANGELOG.md",
            "package.json",
            ".version-bump.json",
        ),
    ),
)
OTHER_GROUP = "Other"


def resolved_commit(root: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot resolve revision {revision}")
    return result.stdout.strip()


def changed_paths(root: Path, base: str, target: str) -> list[str]:
    resolved_commit(root, base)
    resolved_commit(root, target)
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-status", "-M", base, target],
        check=True,
        text=True,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def destination_path(change_line: str) -> str:
    fields = change_line.split("\t")
    if len(fields) < 2:
        raise ValueError(f"invalid git name-status line: {change_line}")
    status = fields[0]
    if (status.startswith("R") or status.startswith("C")) and len(fields) >= 3:
        return fields[2]
    return fields[1]


def classify(change_line: str) -> str:
    path = destination_path(change_line)
    for heading, prefixes in GROUPS:
        if any(path.startswith(prefix) for prefix in prefixes):
            return heading
    return OTHER_GROUP


def render_report(root: Path, base: str, target: str) -> str:
    base_commit = resolved_commit(root, base)
    target_commit = resolved_commit(root, target)
    grouped = {heading: [] for heading, _prefixes in GROUPS}
    grouped[OTHER_GROUP] = []
    for change_line in changed_paths(root, base, target):
        grouped[classify(change_line)].append(change_line)

    lines = [
        "# Upstream change report",
        "",
        f"Base: `{base}` (`{base_commit}`)",
        f"Target: `{target}` (`{target_commit}`)",
        "",
    ]
    for heading in (*[name for name, _prefixes in GROUPS], OTHER_GROUP):
        lines.extend([f"## {heading}", ""])
        changes = sorted(grouped[heading])
        if changes:
            lines.extend(f"- `{change}`" for change in changes)
        else:
            lines.append("_No changes._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the script's parent repository)",
    )
    parser.add_argument("--base-ref", help="base revision; defaults to metadata tag")
    parser.add_argument("--target-ref", required=True, help="target upstream revision")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()

    try:
        if arguments.base_ref:
            base = arguments.base_ref
        else:
            metadata = json.loads(
                (root / ".adaptive-base.json").read_text(encoding="utf-8")
            )
            base = metadata["tag"]
            if not isinstance(base, str) or not base:
                raise ValueError("metadata tag must be a non-empty string")
        report = render_report(root, base, arguments.target_ref)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else str(error)
        print(f"error: git diff failed: {detail}", file=sys.stderr)
        return 1

    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
