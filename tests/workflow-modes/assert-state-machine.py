#!/usr/bin/env python3
"""Validate observable Adaptive workflow event invariants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


VALID_MODES = {"lean", "standard", "strict"}
VALID_OVERRIDES = {"none", *VALID_MODES}


def validate_trace(events: list[dict[str, object]]) -> list[str]:
    errors: list[str] = []
    declaration_count = 0
    active_mode: str | None = None
    override = "none"
    ready = False
    inspection_evidence = False
    final_mutation_index: int | None = None
    verification: tuple[int, bool, int] | None = None

    if not events or events[0].get("event") != "task_start":
        errors.append("trace must begin with task_start")

    for index, event in enumerate(events):
        event_type = event.get("event")

        if event_type == "task_start":
            if index != 0:
                errors.append("task_start may appear only as the first event")
            continue

        if event_type == "mode_declared":
            declaration_count += 1
            mode = event.get("mode")
            selected_override = event.get("override", "none")
            if mode not in VALID_MODES:
                errors.append(f"invalid declared mode: {mode!r}")
                continue
            if selected_override not in VALID_OVERRIDES:
                errors.append(f"invalid user override: {selected_override!r}")
                continue
            if selected_override != "none" and selected_override != mode:
                errors.append("declared mode must match the explicit override")
            active_mode = str(mode)
            override = str(selected_override)
            ready = False
            continue

        if event_type == "inspection":
            evidence = event.get("evidence")
            if isinstance(evidence, str) and evidence.strip():
                inspection_evidence = True
            else:
                errors.append("inspection requires non-empty evidence")
            continue

        if event_type == "warning":
            evidence = event.get("evidence")
            if override not in {"lean", "standard"}:
                errors.append("override warning requires an explicit non-strict override")
            if not isinstance(evidence, str) or not evidence.strip():
                errors.append("override warning requires strict-risk evidence")
            continue

        if event_type == "promotion":
            promoted_mode = event.get("mode")
            evidence = event.get("evidence")
            if promoted_mode != "strict":
                errors.append("automatic mode change must promote to strict")
            if override in {"lean", "standard"}:
                errors.append("explicit non-strict override must warn instead of promoting")
            if active_mode not in {"lean", "standard"}:
                errors.append("promotion requires an active automatic lean or standard mode")
            if (
                not inspection_evidence
                or not isinstance(evidence, str)
                or not evidence.strip()
            ):
                errors.append("promotion requires prior inspection evidence")
            if promoted_mode == "strict" and override == "none":
                active_mode = "strict"
                ready = False
            continue

        if event_type == "readiness":
            readiness_mode = event.get("mode")
            if active_mode is None:
                errors.append("readiness occurred before mode declaration")
            elif readiness_mode != active_mode:
                errors.append(
                    f"readiness mode {readiness_mode!r} does not match active mode {active_mode!r}"
                )
            else:
                ready = True
            continue

        if event_type == "mutation":
            if active_mode is None:
                errors.append("mutation occurred before mode declaration")
            if not ready:
                errors.append("mutation occurred before readiness")
            final_mutation_index = index
            continue

        if event_type == "verification":
            fresh = event.get("fresh") is True
            status = event.get("status")
            if not isinstance(status, int):
                errors.append("verification status must be an integer")
            else:
                verification = (index, fresh, status)
            continue

        if event_type == "completion_claim":
            if verification is None:
                errors.append("completion claim requires fresh successful verification")
                continue
            verification_index, fresh, status = verification
            if not fresh or status != 0:
                errors.append("completion claim requires fresh successful verification")
            if (
                final_mutation_index is not None
                and verification_index < final_mutation_index
            ):
                errors.append("verification must follow the final mutation")
            continue

        errors.append(f"unknown event type: {event_type!r}")

    if declaration_count != 1:
        errors.append(
            f"trace requires exactly one mode declaration; found {declaration_count}"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", default="-", help="JSON trace file or -")
    arguments = parser.parse_args(argv)

    try:
        if arguments.trace == "-":
            document = json.load(sys.stdin)
        else:
            document = json.loads(Path(arguments.trace).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"error: cannot read trace: {error}", file=sys.stderr)
        return 1

    if not isinstance(document, list) or not all(
        isinstance(event, dict) for event in document
    ):
        print("error: trace must be a JSON array of event objects", file=sys.stderr)
        return 1

    errors = validate_trace(document)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("Workflow state trace satisfies Adaptive invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
