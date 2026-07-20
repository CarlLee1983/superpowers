#!/usr/bin/env python3
"""Validate workflow-mode JSONL without counting prompt or tool-input echoes."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any


EXPECTED_MODE = {
    "lean": "lean",
    "standard": "standard",
    "strict": "strict",
    "override": "lean",
    "escalation": "strict",
    "explicit-skill": "lean",
}
DECLARATION = re.compile(r"(?im)^\s*Mode:\s*(lean|standard|strict)\b")
BOOTSTRAP_PATHS = (
    "skills/using-superpowers/SKILL.md",
    "skills/selecting-workflow-mode/SKILL.md",
    "skills/selecting-workflow-mode/references/risk-matrix.md",
)
PAUSE_TOPICS = re.compile(
    r"\b(requirements?|constraints?|design|migration|rollback|approval|approve|"
    r"confirm|clarif\w*|risk|compatib\w*|public|api|payment|billing|amount|"
    r"retain|remove|alias|version|clients?|consumers?)\b",
    re.IGNORECASE,
)


class ValidationError(Exception):
    pass


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValidationError(f"cannot read transcript {path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"invalid JSON on line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(event, dict):
            raise ValidationError(f"JSON value on line {line_number} is not an object")
        events.append(event)

    if not events:
        raise ValidationError("transcript contains no JSON events")
    return events


def validate_claude_plugin(
    init: dict[str, Any], expected_root: Path | None, expected_version: str | None
) -> None:
    if expected_root is None or expected_version is None:
        return
    plugins = init.get("plugins")
    matches = [
        plugin
        for plugin in plugins if isinstance(plugin, dict) and plugin.get("name") == "superpowers"
    ] if isinstance(plugins, list) else []
    valid = []
    for plugin in matches:
        path = plugin.get("path")
        try:
            path_matches = isinstance(path, str) and Path(path).resolve() == expected_root.resolve()
        except OSError:
            path_matches = False
        if (
            path_matches
            and plugin.get("source") == "superpowers@inline"
            and plugin.get("version") == expected_version
        ):
            valid.append(plugin)
    if len(matches) != 1 or len(valid) != 1:
        raise ValidationError(
            "Claude init lacks exactly one expected inline checkout plugin "
            f"(path={str(expected_root)!r}, source='superpowers@inline', "
            f"version={expected_version!r})"
        )


def claude_visible_text(
    events: list[dict[str, Any]],
    expected_model: str,
    expected_plugin_root: Path | None = None,
    expected_plugin_version: str | None = None,
) -> list[str]:
    init_events = [
        event
        for event in events
        if event.get("type") == "system" and event.get("subtype") == "init"
    ]
    if len(init_events) != 1:
        raise ValidationError(
            f"expected exactly one Claude init event; found {len(init_events)}"
        )
    actual_model = init_events[0].get("model")
    if actual_model != expected_model:
        raise ValidationError(
            f"expected model {expected_model}; Claude initialized {actual_model!r}"
        )
    validate_claude_plugin(
        init_events[0], expected_plugin_root, expected_plugin_version
    )

    successes = [
        event
        for event in events
        if event.get("type") == "result" and event.get("subtype") == "success"
    ]
    if len(successes) != 1:
        raise ValidationError(
            f"expected exactly one successful result event; found {len(successes)}"
        )

    texts: list[str] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return texts


def is_claude_bootstrap(block: dict[str, Any]) -> bool:
    name = block.get("name")
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        return False
    if name == "Skill":
        skill = tool_input.get("skill")
        return isinstance(skill, str) and skill.split(":")[-1] in {
            "using-superpowers",
            "selecting-workflow-mode",
        }
    if name == "Read":
        path = tool_input.get("file_path")
        return isinstance(path, str) and path.endswith(
            tuple(f"/{relative}" for relative in BOOTSTRAP_PATHS)
        )
    return False


def split_read_command(command: str) -> list[str] | None:
    if re.search(r"[;&|<>\n`]|\$\(", command):
        return None
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError:
        return None
    if (
        len(arguments) == 3
        and arguments[0] in {"/bin/zsh", "/bin/bash", "/bin/sh"}
        and arguments[1] == "-lc"
    ):
        inner = arguments[2]
        if re.search(r"[;&|<>\n`]|\$\(", inner):
            return None
        try:
            arguments = shlex.split(inner, posix=True)
        except ValueError:
            return None
    return arguments


def exact_bootstrap_path(argument: str, expected_root: Path) -> bool:
    candidate = Path(argument)
    if not candidate.is_absolute():
        return False
    resolved = candidate.resolve()
    allowed = {(expected_root / relative).resolve() for relative in BOOTSTRAP_PATHS}
    return resolved in allowed


def is_codex_bootstrap(command: str, expected_root: Path | None) -> bool:
    if expected_root is None:
        return False
    arguments = split_read_command(command)
    if not arguments:
        return False
    executable = arguments[0]
    if executable in {"cat", "/bin/cat", "/usr/bin/cat"}:
        operands = arguments[1:]
        if operands[:1] == ["--"]:
            operands = operands[1:]
        if not operands or any(operand.startswith("-") for operand in operands):
            return False
    elif executable in {"sed", "/bin/sed", "/usr/bin/sed"}:
        if len(arguments) < 4 or arguments[1] != "-n":
            return False
        if not re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", arguments[2]):
            return False
        operands = arguments[3:]
    else:
        return False
    return all(exact_bootstrap_path(operand, expected_root) for operand in operands)


def validate_declaration_order(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
) -> None:
    declared = False
    active_items: dict[str, tuple[str, str | None]] = {}
    completed_items: set[str] = set()
    for event in events:
        if backend == "claude":
            if event.get("type") != "assistant":
                continue
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and DECLARATION.search(text):
                        declared = True
                elif block.get("type") == "tool_use" and not declared:
                    if not is_claude_bootstrap(block):
                        raise ValidationError(
                            "task-specific action before mode declaration: "
                            f"Claude tool {block.get('name')!r}"
                        )
        else:
            if event.get("type") not in {"item.started", "item.completed"}:
                if event.get("type") != "item.updated":
                    continue
            item = event.get("item")
            if not isinstance(item, dict):
                raise ValidationError("Codex item lifecycle event lacks an item object")
            item_type = item.get("type")
            item_id = item.get("id")
            event_type = event.get("type")
            if not isinstance(item_id, str) or not item_id or not isinstance(item_type, str):
                raise ValidationError("Codex item lifecycle event lacks a stable id/type")
            signature = (
                item_type,
                item.get("command") if isinstance(item.get("command"), str) else None,
            )
            if event_type == "item.started":
                if item_id in active_items or item_id in completed_items:
                    raise ValidationError(f"Codex item lifecycle reused id {item_id!r}")
                if active_items:
                    raise ValidationError(
                        "Codex item lifecycle started a later item before the active item completed"
                    )
                active_items[item_id] = signature
            elif item_type == "agent_message" and event_type == "item.completed":
                if item_id in completed_items:
                    raise ValidationError(f"Codex item lifecycle reused id {item_id!r}")
                if item_id in active_items:
                    if active_items[item_id] != signature:
                        raise ValidationError(
                            f"Codex item lifecycle changed immutable payload for {item_id!r}"
                        )
                    del active_items[item_id]
                elif active_items:
                    raise ValidationError(
                        "Codex item lifecycle completed an out-of-order later item"
                    )
                completed_items.add(item_id)
            else:
                if item_id not in active_items:
                    raise ValidationError(
                        f"Codex item lifecycle {event_type} lacks prior active start"
                    )
                if active_items[item_id] != signature:
                    raise ValidationError(
                        f"Codex item lifecycle changed immutable payload for {item_id!r}"
                    )
                if event_type == "item.completed":
                    del active_items[item_id]
                    completed_items.add(item_id)
            if item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and DECLARATION.search(text):
                    declared = True
                continue
            if declared:
                continue
            if item_type == "command_execution":
                command = item.get("command")
                if isinstance(command, str) and is_codex_bootstrap(
                    command, expected_plugin_root
                ):
                    continue
            raise ValidationError(
                "task-specific action before mode declaration: "
                f"Codex item {item_type!r}"
            )
    if backend == "codex" and active_items:
        raise ValidationError("Codex item lifecycle ended with active item(s)")


def codex_visible_text(events: list[dict[str, Any]]) -> list[str]:
    starts = [event for event in events if event.get("type") == "thread.started"]
    if len(starts) != 1:
        raise ValidationError(
            f"expected exactly one thread.started event; found {len(starts)}"
        )
    completed = [event for event in events if event.get("type") == "turn.completed"]
    if len(completed) != 1:
        raise ValidationError(
            f"expected exactly one turn.completed event; found {len(completed)}"
        )
    failures = [
        event
        for event in events
        if event.get("type") in {"turn.failed", "error"}
    ]
    if failures:
        raise ValidationError(f"Codex transcript contains {len(failures)} failure event(s)")

    texts: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    return texts


def require_pattern(text: str, pattern: str, description: str) -> None:
    if not re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
        raise ValidationError(f"assistant-visible text lacks {description}")


def require_relevant_pause(text: str) -> None:
    sentences = re.split(r"(?<=[?.!])\s+|\n+", text)
    decision_patterns = (
        r"\b(?:which|what)\b.{0,120}\b(?:requirements?|constraints?|rollback|"
        r"design|migration|compatib\w*|clients?|consumers?|api|payment|billing)\b",
        r"\b(?:can|could|would)\s+you\s+(?:please\s+)?"
        r"(?:approve|confirm|clarify|choose|provide|review)\b",
        r"\b(?:please\s+)?(?:approve|confirm|clarify|choose|provide|review)\b",
        r"\b(?:should|shall)\b.{0,120}\b(?:retain|remove|approve|confirm|choose|"
        r"use|migrate|rollback|alias|version|support|proceed|remain)\b",
        r"\bmust\b.{0,120}\b(?:or\s+may|or\s+should|or\s+must)\b",
    )
    for sentence in sentences:
        has_request = re.search(decision_patterns[2], sentence, re.IGNORECASE)
        has_decision = any(
            re.search(pattern, sentence, re.IGNORECASE)
            for pattern in decision_patterns
        )
        if (
            ("?" in sentence or has_request)
            and has_decision
            and PAUSE_TOPICS.search(sentence)
        ):
            return
    raise ValidationError(
        "assistant-visible text lacks relevant clarification/approval pause"
    )


def require_affirmative_brainstorming(text: str) -> None:
    clauses = re.split(r"[.;\n]+|\bbut\b", text, flags=re.IGNORECASE)
    affirmative_patterns = (
        r"\b(?:I|we)\s+(?:am|are|'m|'re|have|will|'ll)?\s*"
        r"(?:using|invoking|running|used|invoked|ran|use|invoke|run)\s+"
        r"(?:the\s+)?brainstorming(?:\s+skill)?\b",
        r"\bbrainstorming\s+skill\s+(?:is|was)\s+(?:loaded|invoked|running|used)\b",
        r"\bbrainstorming\b.{0,100}\b(?:I|we)(?:'ll|\s+will)\s+"
        r"(?:invoke|run|use)\s+(?:that|the)\s+skill\b",
    )
    affirmative = False
    for clause in clauses:
        if re.search(r"\b(?:not|never|without|neither|no)\b", clause, re.IGNORECASE):
            continue
        if any(re.search(pattern, clause, re.IGNORECASE) for pattern in affirmative_patterns):
            affirmative = True
            break
    if not affirmative:
        raise ValidationError(
            "assistant-visible text lacks affirmative brainstorming skill use/invocation"
        )
    candidates: set[str] = set()
    negative = re.compile(
        r"\b(?:reject(?:ed)?|avoid|ruled\s+out|do\s+not\s+use|not\s+an?\s+option)\b",
        re.IGNORECASE,
    )
    label = re.compile(
        r"(?:^|\s)(?:\d+[.)]\s*)?(?:\*\*)?(?:option|candidate)"
        r"(?:\s+\d+)?\s*(?::|is|are)\s*(?:\*\*)?`?"
        r"([A-Za-z_][A-Za-z0-9_-]*)",
        re.IGNORECASE,
    )
    group = re.compile(
        r"\b(?:two|2)?\s*(?:options|candidates)\s*(?:are|:)\s*([^.;\n]+)",
        re.IGNORECASE,
    )
    bullet = re.compile(
        r"^\s*(?:[-*]|\d+[.)])\s+(?:`([A-Za-z_][A-Za-z0-9_-]*)`|"
        r"([a-z][A-Za-z0-9]*(?:[A-Z_][A-Za-z0-9_]*)+))"
    )
    for line in text.splitlines():
        for match in label.finditer(line):
            suffix = line[match.start():]
            if not negative.search(suffix):
                candidates.add(match.group(1))
        group_match = group.search(line)
        if group_match:
            for segment in re.split(r"\s+(?:and|or)\s+|,", group_match.group(1)):
                if negative.search(segment):
                    continue
                identifier = re.search(r"`?([A-Za-z_][A-Za-z0-9_-]*)`?", segment)
                if identifier:
                    candidates.add(identifier.group(1))
        bullet_match = bullet.search(line)
        if bullet_match and not negative.search(line):
            candidates.add(bullet_match.group(1) or bullet_match.group(2))
    if len(candidates) < 2:
        raise ValidationError(
            "assistant-visible brainstorming lacks at least two distinct positive options"
        )


def validate_case(case: str, text: str) -> None:
    if case in {"lean", "standard"}:
        require_pattern(
            text,
            r"\b(evidence|verif\w*|tests?\s+pass)",
            "verification evidence",
        )
    elif case == "strict":
        require_relevant_pause(text)
    elif case == "override":
        require_pattern(text, r"\b(warn|risk|security|authentication)", "high-risk override warning")
    elif case == "escalation":
        require_pattern(
            text,
            r"(?:\b(?:promot|escalat)\w*|"
            r"\bpublic\b.{0,80}\b(?:response|api)\b.{0,80}"
            r"\b(?:shape|compatib\w*|break\w*|chang\w*)\b)",
            "promotion/escalation signal or discovered public compatibility risk",
        )
        require_pattern(text, r"\b(production|public|payment|billing)\b", "discovered high-risk signal")
        require_relevant_pause(text)
    elif case == "explicit-skill":
        require_affirmative_brainstorming(text)


def validate(
    backend: str,
    expected_model: str,
    case: str,
    transcript: Path,
    assistant_output: Path | None = None,
    expected_plugin_root: Path | None = None,
    expected_plugin_version: str | None = None,
) -> str:
    if backend not in {"claude", "codex"}:
        raise ValidationError(f"unknown backend: {backend}")
    if case not in EXPECTED_MODE:
        raise ValidationError(f"unknown case: {case}")

    events = load_jsonl(transcript)
    if backend == "claude":
        blocks = claude_visible_text(
            events,
            expected_model,
            expected_plugin_root,
            expected_plugin_version,
        )
    else:
        blocks = codex_visible_text(events)
    visible = "\n\n".join(blocks)
    if assistant_output is not None:
        assistant_output.write_text(visible + "\n", encoding="utf-8")

    validate_declaration_order(backend, events, expected_plugin_root)

    declarations = DECLARATION.findall(visible)
    if len(declarations) != 1:
        raise ValidationError(
            "expected exactly one assistant-visible mode declaration; "
            f"found {len(declarations)}"
        )
    expected_mode = EXPECTED_MODE[case]
    if declarations[0].lower() != expected_mode:
        raise ValidationError(
            f"expected Mode: {expected_mode}; found Mode: {declarations[0].lower()}"
        )

    validate_case(case, visible)
    return visible


def main(argv: list[str]) -> int:
    if len(argv) not in {5, 6, 8}:
        print(
            "usage: assert-live-mode-result.py "
            "<claude|codex> <model> <case> <transcript.jsonl> "
            "[assistant.txt [plugin-root plugin-version]]",
            file=sys.stderr,
        )
        return 2

    backend, expected_model, case, transcript_name = argv[1:5]
    assistant_output = Path(argv[5]) if len(argv) >= 6 and argv[5] != "-" else None
    expected_plugin_root = Path(argv[6]) if len(argv) == 8 else None
    expected_plugin_version = argv[7] if len(argv) == 8 else None
    try:
        validate(
            backend,
            expected_model,
            case,
            Path(transcript_name),
            assistant_output,
            expected_plugin_root,
            expected_plugin_version,
        )
    except ValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(f"validated assistant-visible Mode: {EXPECTED_MODE[case]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
