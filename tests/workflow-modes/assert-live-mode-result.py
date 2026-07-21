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
    "escalation": "standard",
    "explicit-skill": "lean",
}
DECLARATION = re.compile(r"(?im)^\s*Mode:\s*(lean|standard|strict)\b")
PROMOTION = re.compile(
    r"(?im)^\s*Promoting\s+to\s+(lean|standard|strict)\s+[—-]\s*([^\n]+)"
)
PROMOTION_REASON = re.compile(
    r"\bpayment\b|\bpublic\s+API\b|\bbreaking\b.{0,50}\bcompatib\w*\b",
    re.IGNORECASE,
)
BOOTSTRAP_PATHS = (
    "skills/using-superpowers/SKILL.md",
    "skills/selecting-workflow-mode/SKILL.md",
    "skills/selecting-workflow-mode/references/risk-matrix.md",
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


def is_claude_bootstrap(
    block: dict[str, Any], expected_root: Path | None
) -> bool:
    name = block.get("name")
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        return False
    if name == "Skill":
        skill = tool_input.get("skill")
        return isinstance(skill, str) and skill in {
            "selecting-workflow-mode",
            "superpowers:selecting-workflow-mode",
        }
    if name == "Read":
        path = tool_input.get("file_path")
        if not isinstance(path, str) or expected_root is None:
            return False
        root = expected_root.resolve(strict=False)
        candidate = Path(path)
        allowed_relatives = {
            Path("skills/selecting-workflow-mode/SKILL.md"),
            Path("skills/selecting-workflow-mode/references/risk-matrix.md"),
        }
        if not candidate.is_absolute() or ".." in candidate.parts:
            return False
        try:
            relative = candidate.relative_to(expected_root.absolute())
        except ValueError:
            return False
        if relative not in allowed_relatives:
            return False
        if candidate.resolve(strict=False) != root / relative:
            return False
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return False
        return True
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


def is_read_only_inspection_command(
    command: str, expected_root: Path | None
) -> bool:
    if expected_root is not None and is_codex_bootstrap(command, expected_root):
        return False
    arguments = split_read_command(command)
    if not arguments:
        return False
    executable = Path(arguments[0]).name
    if executable == "cat":
        return len(arguments) > 1
    if executable == "sed":
        return (
            len(arguments) >= 4
            and arguments[1] == "-n"
            and re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", arguments[2])
            is not None
        )
    if executable in {"rg", "grep", "ls", "find", "pwd", "head", "tail", "wc", "stat"}:
        return True
    if executable == "git" and len(arguments) > 1:
        return arguments[1] in {"status", "diff", "log", "show", "ls-files", "grep"}
    return False


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
                    if not is_claude_bootstrap(block, expected_plugin_root):
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


def has_relevant_pause(text: str) -> bool:
    sentences = re.split(r"(?<=[?.!])\s+|\n+", text)
    decision_object_body = (
        r"(?:requirements?|scope|rollback\s+requirements?|"
        r"migration\s+(?:approach|plan|strategy|options?)|"
        r"rollout(?:\s+(?:approach|plan|strategy|options?))?|"
        r"API\s+(?:compatibility|contract(?:\s+change)?|changes?|versions?|"
        r"breaking\s+change)|compatibility(?:\s+(?:requirements?|plan|"
        r"aliases?))?|breaking\s+(?:API\s+)?(?:change|release)|"
        r"deprecation\s+window|schema\s+(?:change|conversion|migration)|"
        r"data\s+(?:conversion|migration)|named\s+(?:option|choice)\s+"
        r"`?[A-Za-z_][A-Za-z0-9_-]*`?|(?:option|choice)\s+"
        r"`?[A-Za-z_][A-Za-z0-9_-]*`?|existing\s+API\s+clients?"
        r".{0,60}\balias|(?:retain|remove|preserve)\w*.{0,50}\balias|"
        r"amount\s+alias|old\s+amount\s+key.{0,80}\bcompatibility\s+alias)"
    )
    decision_object = (
        rf"(?<![A-Za-z0-9_]){decision_object_body}(?![A-Za-z0-9_])"
    )
    decision_target = (
        rf"(?:(?:the|this|that|a|an|proposed|payment)\s+)*{decision_object}"
    )
    task_action = (
        r"(?:use|choose|adopt|retain|remove|preserve|approve|implement|"
        r"proceed\s+with|roll\s+out)"
    )
    decision_forms = (
        rf"^\s*which\s+{decision_target}\s+should\s+(?:I|we)\s+"
        rf"(?:use|choose|follow)\s*\?\s*$",
        rf"^\s*which\s+{decision_target}\s+do\s+you\s+"
        rf"(?:want|prefer)\s*\?\s*$",
        rf"^\s*which\s+{decision_target}\s+applies\s+to\s+"
        rf"(?:this|the)\s+migration\s*\?\s*$",
        rf"^\s*should\s+(?:I|we)\s+{task_action}\s+"
        rf"{decision_target}[^?]*\?\s*$",
        rf"^\s*do\s+you\s+want\s+(?:me|us)\s+to\s+{task_action}\s+"
        rf"{decision_target}[^?]*\?\s*$",
        rf"^\s*would\s+you\s+like\s+(?:me|us)\s+to\s+{task_action}\s+"
        rf"{decision_target}[^?]*\?\s*$",
        rf"^\s*(?:can|could)\s+you\s+(?:please\s+)?"
        rf"(?:confirm|clarify|choose|approve|decide|provide)\s+"
        rf"(?:whether\s+)?{decision_target}[^?]*\?\s*$",
        rf"^\s*please\s+(?:confirm|clarify|choose|approve|decide|provide)\s+"
        rf"{decision_target}[^.!?]*(?:[.!]|$)\s*$",
        rf"^\s*(?:I|we)\s+(?:need|await)\s+your\s+"
        rf"(?:approval|decision|confirmation|clarification)\s+"
        rf"(?:on|about|for)\s+{decision_target}[^.!?]*"
        rf"\bbefore\s+proceeding(?:[.!]|$)\s*$",
        rf"^\s*(?:first\s+decision:\s*)?must\s+{decision_target}[^?]*"
        rf"\bor\s+may\b[^?]*\?\s*$",
        r"^\s*(?:first\s+decision:\s*)?must\s+existing\s+API\s+clients?"
        r"[^?]*\bdeprecation\s+window\b[^?]*\bor\s+may\b[^?]*"
        r"\bbreaking\s+release\b[^?]*\?\s*$",
        r"^\s*should\s+(?:the\s+)?old\s+amount\s+key\b[^?]*\bor\b[^?]*"
        r"\bcompatibility\s+alias\b[^?]*\?\s*$",
        rf"^\s*should\s+{decision_target}[^?]*\bor\b[^?]*\?\s*$",
    )
    for sentence in sentences:
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in decision_forms):
            return True
    return False


def require_relevant_pause(text: str) -> None:
    if has_relevant_pause(text):
        return
    raise ValidationError(
        "assistant-visible text lacks relevant clarification/approval pause"
    )


def escalation_records(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    if backend == "claude":
        for event in events:
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
                    value = block.get("text")
                    if isinstance(value, str):
                        records.append(("text", value))
                    continue
                if block.get("type") != "tool_use":
                    continue
                if is_claude_bootstrap(block, expected_plugin_root):
                    continue
                name = block.get("name")
                tool_input = block.get("input")
                if name in {"Read", "Glob", "Grep"}:
                    records.append(("inspection", str(name)))
                elif name == "Bash" and isinstance(tool_input, dict):
                    command = tool_input.get("command")
                    if isinstance(command, str) and is_read_only_inspection_command(
                        command, expected_plugin_root
                    ):
                        records.append(("inspection", command))
                    else:
                        records.append(("mutation", str(name)))
                elif name in {"Edit", "Write", "NotebookEdit"}:
                    records.append(("mutation", str(name)))
        return records

    for event in events:
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if event.get("type") == "item.completed" and item_type == "agent_message":
            value = item.get("text")
            if isinstance(value, str):
                records.append(("text", value))
        elif event.get("type") == "item.started" and item_type == "command_execution":
            command = item.get("command")
            if not isinstance(command, str):
                records.append(("mutation", "command_execution"))
            elif is_codex_bootstrap(command, expected_plugin_root):
                continue
            elif is_read_only_inspection_command(command, expected_plugin_root):
                records.append(("inspection", command))
            else:
                records.append(("mutation", command))
        elif event.get("type") == "item.started" and item_type == "file_change":
            records.append(("mutation", str(item_type)))
    return records


def validate_escalation_order(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
) -> None:
    inspection_seen = False
    promotion_seen = False
    pause_seen = False
    promotion_count = 0
    for kind, value in escalation_records(backend, events, expected_plugin_root):
        if kind == "inspection":
            inspection_seen = True
            continue
        if kind == "mutation":
            if not promotion_seen or not pause_seen:
                raise ValidationError(
                    "escalation mutation before strict promotion/approval pause"
                )
            continue

        matches = list(PROMOTION.finditer(value))
        if matches:
            for match in matches:
                promotion_count += 1
                if promotion_count > 1:
                    raise ValidationError(
                        "escalation requires exactly one promotion to strict"
                    )
                if match.group(1).lower() != "strict":
                    raise ValidationError("escalation requires promotion to strict")
                if not PROMOTION_REASON.search(match.group(2)):
                    raise ValidationError(
                        "strict promotion lacks payment/public API/breaking compatibility reason"
                    )
                if not inspection_seen:
                    raise ValidationError(
                        "strict promotion occurred before project inspection"
                    )
                promotion_seen = True
                if has_relevant_pause(value[match.end() :]):
                    pause_seen = True
        elif promotion_seen and has_relevant_pause(value):
            pause_seen = True

    if not inspection_seen:
        raise ValidationError(
            "escalation lacks project inspection after initial declaration"
        )
    if not promotion_seen:
        raise ValidationError("escalation lacks promotion to strict")
    if not pause_seen:
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
    negative_patterns = (
        r"\b(?:I|we)\s+(?:(?:am|are|was|were|have|has|had|do|does|did|"
        r"will|would|can|could|'m|'re|'ve|'ll)\s+)?(?:not|never)\s+"
        r"(?:actually\s+)?(?:using|invoking|running|used|invoked|ran|use|"
        r"invoke|run)\s+(?:the\s+)?brainstorming(?:\s+skill)?\b",
        r"\b(?:I|we)\s+(?:won't|wouldn't|can't|couldn't|don't|doesn't|didn't)\s+"
        r"(?:actually\s+)?(?:use|invoke|run)\s+(?:the\s+)?"
        r"brainstorming(?:\s+skill)?\b",
        r"\b(?:not|never)\s+(?:actually\s+)?(?:using|invoking|running|used|"
        r"invoked|run)\s*,?\s*(?:the\s+)?brainstorming(?:\s+skill)?\b",
        r"\bbrainstorming\s+skill\s+(?:is|was|will\s+be)\s+not\s+"
        r"(?:used|invoked|run|running)\b",
        r"\b(?:I|we)\s+(?:(?:am|are|was|were)\s+)?(?:not|no\s+longer)\s+"
        r"(?:actually\s+)?(?:using|invoking|running|use|invoke|run)\s+"
        r"(?:it|that\s+skill|the\s+skill)\b",
        r"\b(?:I|we)\s+(?:won't|wouldn't|can't|couldn't|don't|doesn't|didn't)\s+"
        r"(?:actually\s+)?(?:use|invoke|run)\s+"
        r"(?:it|that\s+skill|the\s+skill)\b",
        r"\b(?:not|no\s+longer)\s+(?:actually\s+)?"
        r"(?:using|invoking|running|use|invoke|run)\s+"
        r"(?:it|that\s+skill|the\s+skill)\b",
    )
    affirmative_seen = False
    negated_after_affirmative = False
    for clause in clauses:
        is_negative = any(
            re.search(pattern, clause, re.IGNORECASE)
            for pattern in negative_patterns
        )
        is_affirmative = any(
            re.search(pattern, clause, re.IGNORECASE)
            for pattern in affirmative_patterns
        )
        if is_negative and affirmative_seen:
            negated_after_affirmative = True
        elif is_affirmative and not is_negative:
            affirmative_seen = True
    if not affirmative_seen or negated_after_affirmative:
        raise ValidationError(
            "assistant-visible text lacks affirmative brainstorming skill use/invocation"
        )
    candidates: set[str] = set()
    negative_status = re.compile(
        r"\b(?:reject(?:ed)?|avoid|ruled\s+out|do\s+not\s+use|"
        r"not\s+an?\s+option|not\s+recommended|current[- ]only|"
        r"struck|strikeout|strikethrough)\b",
        re.IGNORECASE,
    )
    label = re.compile(
        r"^\s*(?:(?:[-*]|\d+[.)])\s+(?:\*\*)?"
        r"(?:option|candidate)(?:\s+\d+)?|(?:\*\*)?"
        r"(?:option|candidate)\s+\d+)\s*:\s*(?:\*\*)?`?"
        r"([A-Za-z_][A-Za-z0-9_-]*)",
        re.IGNORECASE,
    )
    group = re.compile(
        r"\b(?:two|2)?\s*(?:options|candidates)\s*(?:are|:)\s*([^.;\n]+)",
        re.IGNORECASE,
    )

    def negative_candidate(unit: str, identifier: str | None = None) -> bool:
        status_text = re.sub(
            r"\bkeep(?:ing)?\s+the\s+current\s+name\b",
            "",
            unit,
            flags=re.IGNORECASE,
        )
        has_current_status = re.search(
            r"(?:^|[(:—-])\s*(?:current|existing)\b|"
            r"\b(?:current|existing)\s+(?:name|identifier|option|candidate)\b",
            status_text,
            re.IGNORECASE,
        )
        return bool(
            "~~" in unit
            or negative_status.search(status_text)
            or has_current_status
            or (
                identifier is not None
                and identifier.lower().startswith(("current", "existing"))
            )
        )

    for line in text.splitlines():
        for unit in line.split(";"):
            group_match = group.search(unit)
            if group_match:
                group_prefix = unit[: group_match.start()]
                if negative_candidate(group_prefix):
                    continue
                for segment in re.split(
                    r"\s*,\s*(?:and\s+)?|\s+(?:and|or)\s+",
                    group_match.group(1),
                ):
                    identifier_match = re.fullmatch(
                        r"\s*`?([A-Za-z_][A-Za-z0-9_-]*)`?"
                        r"(?:\s*\([^)]*\))?\s*",
                        segment,
                    )
                    if identifier_match and not negative_candidate(
                        segment, identifier_match.group(1)
                    ):
                        candidates.add(identifier_match.group(1))
                continue
            if negative_candidate(unit):
                continue
            label_match = label.search(unit)
            if not label_match or negative_candidate(unit, label_match.group(1)):
                continue
            candidates.add(label_match.group(1))
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

    if case == "escalation":
        validate_escalation_order(backend, events, expected_plugin_root)
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
