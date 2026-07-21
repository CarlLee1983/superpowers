#!/usr/bin/env python3
"""Validate workflow-mode JSONL without counting prompt or tool-input echoes."""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass
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
    r"(?i)^Promoting\s+to\s+(lean|standard|strict)\s+—\s*([^\n]+)$"
)
WORKFLOW_TRANSITION = re.compile(
    r"\b(?P<verb>promot(?:e|es|ed|ing)|escalat(?:e|es|ed|ing)|"
    r"rais(?:e|es|ed|ing)|upgrad(?:e|es|ed|ing)|"
    r"demot(?:e|es|ed|ing)|lower(?:s|ed|ing)?|"
    r"downgrad(?:e|es|ed|ing)|switch(?:es|ed|ing)|"
    r"mov(?:e|es|ed|ing)|transition(?:s|ed|ing)?)"
    r"(?:\s+(?:(?:the|our|my|your|their)\s+)?"
    r"(?:(?:active|current)\s+)?(?:workflows?|modes?))?\s+"
    r"(?:(?:from\s+(?:lean|standard|strict)\s+)?(?:back\s+)?(?:to|into))\s+"
    r"(?P<mode>lean|standard|strict)\b",
    re.IGNORECASE,
)
BOOTSTRAP_PATHS = (
    "skills/using-superpowers/SKILL.md",
    "skills/selecting-workflow-mode/SKILL.md",
    "skills/selecting-workflow-mode/references/risk-matrix.md",
)
REQUIRED_ESCALATION_INSPECTIONS = {"src/schema.js", "src/billing.js"}


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


def project_path(
    value: object,
    expected_project_root: Path,
    *,
    require_file: bool = False,
    require_directory: bool = False,
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = Path(value)
    if ".." in raw.parts:
        return None
    candidate = raw if raw.is_absolute() else expected_project_root / raw
    try:
        root = expected_project_root.resolve(strict=True)
        lexical_root = expected_project_root.absolute()
        absolute_candidate = candidate.absolute()
        relative = None
        path_root = None
        for allowed_root in (lexical_root, root):
            try:
                relative = absolute_candidate.relative_to(allowed_root)
                path_root = allowed_root
                break
            except ValueError:
                continue
        if relative is None or path_root is None:
            return None
        current = path_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return None
        resolved = candidate.resolve(strict=require_file or require_directory)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if require_file and not resolved.is_file():
        return None
    if require_directory and not resolved.is_dir():
        return None
    return resolved


def valid_claude_inspection(
    name: object, tool_input: object, expected_project_root: Path
) -> bool:
    if not isinstance(tool_input, dict):
        return False
    if name == "Read":
        return project_path(
            tool_input.get("file_path"),
            expected_project_root,
            require_file=True,
        ) is not None
    if name not in {"Glob", "Grep"}:
        return False
    pattern = tool_input.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip() or "\x00" in pattern:
        return False
    return project_path(
        tool_input.get("path"),
        expected_project_root,
        require_directory=True,
    ) is not None


def safe_claude_read_probe(tool_input: object, expected_project_root: Path) -> bool:
    return isinstance(tool_input, dict) and project_path(
        tool_input.get("file_path"), expected_project_root
    ) is not None


def safe_project_glob_paths(
    pattern: str, expected_project_root: Path
) -> tuple[str, ...] | None:
    lexical = Path(pattern)
    if (
        lexical.is_absolute()
        or ".." in lexical.parts
        or pattern.count("*") != 1
        or re.fullmatch(r"[A-Za-z0-9._/-]*\*[A-Za-z0-9._/-]*", pattern) is None
    ):
        return None
    root = expected_project_root.resolve(strict=True)
    try:
        matches = sorted(
            expected_project_root.glob(pattern), key=lambda path: path.as_posix()
        )
    except (OSError, ValueError):
        return None
    paths: list[str] = []
    for match in matches:
        resolved = project_path(str(match), expected_project_root, require_file=True)
        if resolved is None:
            return None
        paths.append(resolved.relative_to(root).as_posix())
    return tuple(paths)


def project_operand_paths(
    arguments: list[str],
    expected_project_root: Path,
    *,
    require_file: bool,
) -> tuple[str, ...] | None:
    if not arguments:
        return None
    root = expected_project_root.resolve(strict=True)
    paths: list[str] = []
    unmatched_glob = False
    for argument in arguments:
        if Path(argument).is_absolute():
            return None
        if re.search(r"[?\[\]{}~$]", argument):
            return None
        if "*" in argument:
            expanded = safe_project_glob_paths(argument, expected_project_root)
            if expanded is None:
                return None
            if not expanded:
                unmatched_glob = True
                continue
            paths.extend(expanded)
            continue
        resolved = project_path(
            argument,
            expected_project_root,
            require_file=require_file,
        )
        if resolved is None:
            return None
        if not require_file and resolved.exists() and not resolved.is_file():
            return None
        paths.append(resolved.relative_to(root).as_posix())
    return () if unmatched_glob else tuple(paths)


def inspection_command_paths(
    command: str,
    expected_root: Path | None,
    expected_project_root: Path,
    *,
    require_files: bool = True,
) -> tuple[str, ...] | None:
    if "\\" in command:
        return None
    if expected_root is not None and is_codex_bootstrap(command, expected_root):
        return None
    arguments = split_read_command(command)
    if not arguments:
        return None
    executable = arguments[0]
    if executable == "cat":
        operands = arguments[1:]
        if any(operand.startswith("-") for operand in operands):
            return None
        return project_operand_paths(
            operands,
            expected_project_root,
            require_file=require_files,
        )
    if executable == "sed":
        operands = arguments[3:]
        if (
            len(arguments) < 4
            or arguments[1] != "-n"
            or re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", arguments[2])
            is None
            or any(operand.startswith("-") for operand in operands)
        ):
            return None
        return project_operand_paths(
            operands,
            expected_project_root,
            require_file=require_files,
        )
    return None


def is_read_only_inspection_command(
    command: str,
    expected_root: Path | None,
    expected_project_root: Path,
    *,
    require_files: bool = True,
) -> bool:
    return inspection_command_paths(
        command,
        expected_root,
        expected_project_root,
        require_files=require_files,
    ) is not None


def inspection_command_uses_glob(command: str) -> bool:
    arguments = split_read_command(command)
    if not arguments:
        return False
    if arguments[0] == "cat":
        operands = arguments[1:]
    elif arguments[0] == "sed":
        operands = arguments[3:]
    else:
        return False
    return any("*" in operand for operand in operands)


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
    current_system_question = re.search(
        r"(?:\*\*)?what\s+does\s+(?:the\s+)?"
        r"(?:payment|billing|financial)\s+system\s+look\s+like\s+today\?"
        r"(?:\*\*)?",
        text,
        re.IGNORECASE,
    )
    if current_system_question is not None:
        requirement_signals = (
            r"\b(?:relational\s+DB|document\s+store|Postgres|MySQL|Mongo|Dynamo)\b",
            r"\b(?:column\s+type|amount\s+column|DECIMAL|NUMERIC|float)\b",
            r"\b(?:REST\s+API|API\s+shape|API\s+(?:returns?|response))\b",
            r"\b(?:external|internal|first-party)\b.{0,40}\b(?:consumer|client)",
        )
        if all(
            re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            for pattern in requirement_signals
        ):
            return True
    decision_object_body = (
        r"(?:requirements?|scope|rollback\s+requirements?|"
        r"migration\s+(?:approach|plan|strategy|options?)|"
        r"rollout(?:\s+(?:approach|plan|strategy|options?))?|"
        r"public\s+API\s+transition|"
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
        r"^\s*(?:before\s+making\s+any\s+change,\s+i\s+need\s+your\s+"
        r"call:\s*)?should\s+(?:I|we)\s+proceed\s+in\s+strict\s+mode\b"
        r"(?=[^?]*\b(?:rename|public\s+response|amountCents)\b)[^?]*\?\s*$",
        r"^\s*(?:before\s+the\s+first\s+mutation,\s+i\s+need\s+your\s+"
        r"decision:\s*)?should\s+(?:I|we)\s+proceed\s+with\s+"
        r"(?=[^?]*\bamount\b)(?=[^?]*\bamountCents\b)"
        r"[^?]*\brename\b[^?]*\bin\s+strict\s+mode\s*\?\s*$",
        r"^\s*(?:before\s+making\s+any\s+change,\s+[^:?]+:\s*)?"
        r"do\s+you\s+want\s+me\s+to\s+proceed\s+with\s+the\s+rename\s+"
        r"in\s+strict\s+mode\b[^?]*\?\s*$",
        r"^\s*(?:i['’]m\s+pausing\s+before\s+making\s+any\s+change:\s*)?"
        r"do\s+you\s+want\s+me\s+to\s+proceed\s+with\s+the\s+rename\s+"
        r"in\s+strict\s+mode\s*\?\s*$",
        r"^\s*(?:before\s+i\s+make\s+any\s+changes,\s+please\s+confirm:\s*)?"
        r"do\s+you\s+want\s+to\s+proceed\s+in\s+strict\s+mode\s+with\s+"
        r"(?:this|the)\s+rename\s*\?\s*$",
        r"^\s*proceed\s+in\s+strict\s+mode\s+with\s+the\s+rename\s+and\s+"
        r"consumer\s+updates\s*\?\s*$",
    )
    for sentence in sentences:
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in decision_forms):
            return True
        if "?" not in sentence:
            continue
        if re.search(r"\bstrict\s+mode\b", sentence, re.IGNORECASE) is None:
            continue
        if re.search(
            r"\b(?:should|shall|proceed|which|confirm|approve)\b|"
            r"\bdo\s+you\s+want\b",
            sentence,
            re.IGNORECASE,
        ) is None:
            continue
        if re.search(
            r"\b(?:rename|amountcents|compatibility|schema)\b|"
            r"\bpublic\s+response\b|\bresponse\s+field\b",
            sentence,
            re.IGNORECASE,
        ) is not None:
            return True
    return False


def require_relevant_pause(text: str) -> None:
    if has_relevant_pause(text):
        return
    raise ValidationError(
        "assistant-visible text lacks relevant clarification/approval pause"
    )


def has_concrete_discovery_pause(text: str) -> bool:
    question = re.search(
        r"(?mi)^\s*(?:\*\*)?((?:where|what|which|how)\b[^?\n]*"
        r"(?:system|stack|migration|public\s+API|API)\b[^?\n]*\?)",
        text,
    )
    if question is None:
        return False
    question_text = question.group(1)
    if re.search(
        r"\b(?:live|stack|expose|store|format|transition|version|migrat\w*|"
        r"architecture|implementation|look\s+like|use)\b",
        question_text,
        re.IGNORECASE,
    ) is None:
        return False

    high_risk_signals = (
        r"\b(?:payment|billing|finance|amount|dollars?|cents?)\b",
        r"\b(?:production|data\s+migration|schema|migration|backfill)\b",
        r"\b(?:public\s+API|compatibility|breaking|API\s+versioning?)\b",
    )
    if sum(
        re.search(pattern, text, re.IGNORECASE) is not None
        for pattern in high_risk_signals
    ) < 2:
        return False

    option_pattern = re.compile(
        r"(?m)^\s*(?:[-*]\s+)?(?:\*\*)?([A-Z]|\d+)[.)]"
        r"(?:\*\*)?\s+(.+)$"
    )
    concrete_signal = re.compile(
        r"`[A-Za-z_][^`]*`|\b(?:Postgres|MySQL|REST|database|framework|"
        r"schema|migration\s+scripts?|API|runbook|design\s+document|integer|"
        r"dollars?|cents?|versioned|v\d+)\b",
        re.IGNORECASE,
    )
    negative_option = re.compile(
        r"^\s*(?:\*\*)?(?:no|none|not|neither|without)\b",
        re.IGNORECASE,
    )
    option_lines = text[question.end():].splitlines()
    line_index = 0
    introductory_line_seen = False
    while line_index < len(option_lines):
        line = option_lines[line_index]
        if not line.strip():
            line_index += 1
            continue
        if option_pattern.fullmatch(line) is not None:
            break
        if (
            not introductory_line_seen
            and line.strip().endswith("?")
            and re.search(r"\b(?:which|options?|matches?)\b", line, re.IGNORECASE)
        ):
            introductory_line_seen = True
            line_index += 1
            continue
        break
    options: list[tuple[str, str]] = []
    while line_index < len(option_lines):
        line = option_lines[line_index]
        option_match = option_pattern.fullmatch(line)
        if option_match is not None:
            options.append((option_match.group(1), option_match.group(2)))
            line_index += 1
            continue
        if not line.strip():
            next_index = line_index
            while (
                next_index < len(option_lines)
                and not option_lines[next_index].strip()
            ):
                next_index += 1
            if (
                next_index < len(option_lines)
                and option_pattern.fullmatch(option_lines[next_index]) is not None
            ):
                line_index = next_index
                continue
            break
        if options and re.match(r"^\s{2,}\S", line):
            label, option = options[-1]
            options[-1] = (label, f"{option} {line.strip()}")
            line_index += 1
            continue
        break
    if len(options) < 2:
        return False
    labels = [label.casefold() for label, _ in options]
    normalized_options = [
        re.sub(r"[^a-z0-9_]+", " ", option.casefold()).strip()
        for _, option in options
    ]
    if len(set(labels)) != len(labels) or len(set(normalized_options)) != len(options):
        return False
    concrete_negative_alternative = re.compile(
        r"[;:—]\s*(?:use|adopt|keep|build|create|provide|run|rely\s+on)\b(.+)$",
        re.IGNORECASE,
    )
    for _, option in options:
        if concrete_signal.search(option) is None:
            return False
        if re.match(
            r"^\s*(?:review|inspect|read|check|analyze|investigate|explore|"
            r"audit|search|look\s+(?:at|for|through))\b",
            option,
            re.IGNORECASE,
        ):
            return False
        if negative_option.search(option):
            alternative = concrete_negative_alternative.search(option)
            if alternative is None or concrete_signal.search(alternative.group(0)) is None:
                return False

    if re.search(r"\bexpose\b", question_text, re.IGNORECASE):
        responsive_signal = re.compile(
            r"`[A-Za-z_][^`]*`|\b(?:amount|field|value|integer|dollars?|cents?|"
            r"versioned|v\d+|endpoint|interface|in[- ]place|response)\b",
            re.IGNORECASE,
        )
    elif re.search(
        r"\b(?:public\s+API|API)\b", question_text, re.IGNORECASE
    ):
        responsive_signal = re.compile(
            r"`[A-Za-z_][^`]*`|\b(?:REST|database|runbook|internal|external|"
            r"endpoint|interface|versioned|v\d+|schema|migration)\b",
            re.IGNORECASE,
        )
    else:
        responsive_signal = re.compile(
            r"\b(?:system|repo|Postgres|MySQL|REST|database|framework|"
            r"implementation|schema|migration|API|runbook|document)\b",
            re.IGNORECASE,
        )
    return all(responsive_signal.search(option) for _, option in options)


def require_strict_pause(text: str) -> None:
    if has_relevant_pause(text) or has_concrete_discovery_pause(text):
        return
    raise ValidationError(
        "assistant-visible text lacks relevant clarification/approval pause"
    )


@dataclass(frozen=True)
class EscalationRecord:
    kind: str
    value: str
    event_index: int
    record_order: int


@dataclass(frozen=True)
class ProseLine:
    text: str
    event_index: int
    record_order: int
    line_index: int
    contextual: bool = False
    qualifier: bool = False


class MarkdownProseStream:
    FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
    LEADING_QUALIFIER = re.compile(
        r"(?i)^\s*(?:(?:documentation|docs?)\s+)?(?:example|quotation|quote)"
        r"(?:\s+from\s+a\s+transcript)?\s*:\s*$|"
        r"^\s*(?:documentation|docs?)\s+example\s*:\s*$",
        re.IGNORECASE,
    )
    TRAILING_QUALIFIER = re.compile(
        r"(?i)^\s*the\s+(?:preceding|previous|above)\s+"
        r"(?:statement|line|promotion(?:\s+statement)?)\s+is\s+"
        r"(?:only\s+)?(?:an?\s+)?(?:(?:unrelated|documentation)\s+)*"
        r"(?:example|quotation|quote|documentation)(?:\s+example)?[.!]?\s*$"
    )

    def __init__(self) -> None:
        self.fence_character: str | None = None
        self.fence_length = 0
        self.pending_qualifier = False

    def consume(self, record: EscalationRecord) -> list[ProseLine]:
        prose: list[ProseLine] = []
        for line_index, line in enumerate(record.value.splitlines()):
            marker = self.FENCE.match(line)
            if self.fence_character is not None:
                if marker:
                    run = marker.group(1)
                    suffix = marker.group(2)
                    if (
                        run[0] == self.fence_character
                        and len(run) >= self.fence_length
                        and not suffix.strip()
                    ):
                        self.fence_character = None
                        self.fence_length = 0
                continue
            if marker:
                run = marker.group(1)
                self.fence_character = run[0]
                self.fence_length = len(run)
                continue
            if line.startswith(("    ", "\t")):
                continue
            if re.match(r"^ {0,3}>", line):
                continue
            if not line.strip():
                prose.append(
                    ProseLine(
                        line,
                        record.event_index,
                        record.record_order,
                        line_index,
                    )
                )
                continue
            if self.LEADING_QUALIFIER.fullmatch(line):
                self.pending_qualifier = True
                prose.append(
                    ProseLine(
                        line,
                        record.event_index,
                        record.record_order,
                        line_index,
                        qualifier=True,
                    )
                )
                continue
            trailing_qualifier = self.TRAILING_QUALIFIER.fullmatch(line) is not None
            prose.append(
                ProseLine(
                    line,
                    record.event_index,
                    record.record_order,
                    line_index,
                    contextual=self.pending_qualifier,
                    qualifier=trailing_qualifier,
                )
            )
            self.pending_qualifier = False
        return prose


def escalation_records(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
    expected_project_root: Path,
    *,
    action_context: str = "escalation",
) -> list[EscalationRecord]:
    records: list[EscalationRecord] = []
    record_order = 0

    def add(kind: str, value: str, event_index: int) -> None:
        nonlocal record_order
        records.append(EscalationRecord(kind, value, event_index, record_order))
        record_order += 1

    if backend == "claude":
        tool_uses: dict[str, tuple[str, tuple[str, ...]]] = {}
        completed_tool_uses: set[str] = set()
        observed_tool_results: set[str] = set()
        for event_index, event in enumerate(events):
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if event.get("type") == "assistant" and block_type == "text":
                    value = block.get("text")
                    if isinstance(value, str):
                        add("text", value, event_index)
                    continue
                if event.get("type") == "assistant" and block_type == "tool_use":
                    tool_id = block.get("id")
                    if not isinstance(tool_id, str) or not tool_id:
                        add("invalid", "Claude tool_use lacks stable id", event_index)
                        continue
                    if tool_id in tool_uses:
                        add("invalid", f"Claude tool_use reused id {tool_id!r}", event_index)
                        continue
                    if is_claude_bootstrap(block, expected_plugin_root):
                        tool_uses[tool_id] = ("bootstrap", ())
                        continue
                    name = block.get("name")
                    tool_input = block.get("input")
                    if (
                        action_context == "standard"
                        and name == "Skill"
                        and isinstance(tool_input, dict)
                        and tool_input.get("skill")
                        == "superpowers:test-driven-development"
                        and set(tool_input).issubset({"skill", "args"})
                        and (
                            "args" not in tool_input
                            or isinstance(tool_input.get("args"), str)
                        )
                    ):
                        tool_uses[tool_id] = ("standard_skill", ())
                    elif name in {"Read", "Glob", "Grep"}:
                        if valid_claude_inspection(
                            name, tool_input, expected_project_root
                        ):
                            paths: tuple[str, ...] = ()
                            if name == "Read" and isinstance(tool_input, dict):
                                resolved = project_path(
                                    tool_input.get("file_path"),
                                    expected_project_root,
                                    require_file=True,
                                )
                                if resolved is not None:
                                    paths = (
                                        resolved.relative_to(
                                            expected_project_root.resolve(strict=True)
                                        ).as_posix(),
                                    )
                            tool_uses[tool_id] = (
                                "inspection" if name == "Read" else "discovery",
                                paths,
                            )
                        elif name == "Read" and safe_claude_read_probe(
                            tool_input, expected_project_root
                        ):
                            tool_uses[tool_id] = ("inspection_probe", ())
                        else:
                            tool_uses[tool_id] = ("invalid", ())
                            add("invalid", f"invalid project inspection: {name}", event_index)
                    elif name == "Bash" and isinstance(tool_input, dict):
                        command = tool_input.get("command")
                        if isinstance(command, str) and is_read_only_inspection_command(
                            command,
                            expected_plugin_root,
                            expected_project_root,
                        ):
                            paths = inspection_command_paths(
                                command,
                                expected_plugin_root,
                                expected_project_root,
                            )
                            tool_uses[tool_id] = ("inspection", paths or ())
                        else:
                            tool_uses[tool_id] = ("mutation", ())
                            add("mutation", str(name), event_index)
                    elif name in {"Edit", "Write", "NotebookEdit"}:
                        tool_uses[tool_id] = ("mutation", ())
                        add("mutation", str(name), event_index)
                    else:
                        tool_uses[tool_id] = ("invalid", ())
                        add(
                            "invalid",
                            f"unrecognized {action_context} action: {name!r}",
                            event_index,
                        )
                    continue
                if block_type != "tool_result":
                    continue
                tool_id = block.get("tool_use_id")
                if isinstance(tool_id, str):
                    observed_tool_results.add(tool_id)
                if not (
                    event.get("type") == "user"
                    and isinstance(message, dict)
                    and message.get("role") == "user"
                ):
                    add(
                        "invalid",
                        "Claude inspection requires a user-role tool result",
                        event_index,
                    )
                    continue
                if not isinstance(tool_id, str) or tool_id not in tool_uses:
                    add("invalid", "tool result lacks matching tool_use id", event_index)
                    continue
                if tool_id in completed_tool_uses:
                    add("invalid", f"duplicate tool result for {tool_id!r}", event_index)
                    continue
                completed_tool_uses.add(tool_id)
                tool_kind, inspection_paths = tool_uses[tool_id]
                if tool_kind in {"inspection", "inspection_probe", "discovery"}:
                    if "is_error" in block and type(block["is_error"]) is not bool:
                        add(
                            "invalid",
                            "inspection tool result is_error must be a JSON boolean",
                            event_index,
                        )
                    elif block.get("is_error") is True:
                        continue
                    elif tool_kind == "inspection":
                        for path in inspection_paths:
                            add("inspection", path, event_index)
                    elif tool_kind == "discovery":
                        add("discovery", tool_id, event_index)
                    else:
                        add(
                            "invalid",
                            f"inspection probe claimed success for missing path {tool_id!r}",
                            event_index,
                        )
                elif tool_kind == "standard_skill":
                    is_error = block.get("is_error", False)
                    metadata = event.get("tool_use_result")
                    metadata_valid = metadata is None or (
                        isinstance(metadata, dict)
                        and type(metadata.get("success")) is bool
                        and metadata.get("success") is True
                        and metadata.get("commandName")
                        == "superpowers:test-driven-development"
                    )
                    if (
                        type(is_error) is not bool
                        or is_error is True
                        or not metadata_valid
                    ):
                        add(
                            "invalid",
                            "standard workflow Skill did not complete successfully",
                            event_index,
                        )
        missing_results = [
            tool_id
            for tool_id, (kind, _) in tool_uses.items()
            if kind in {
                "inspection",
                "inspection_probe",
                "discovery",
                "standard_skill",
            }
            and tool_id not in observed_tool_results
        ]
        if missing_results:
            records.insert(
                0,
                EscalationRecord(
                    "invalid",
                    f"inspection tool result missing for {missing_results[0]!r}",
                    -1,
                    -1,
                ),
            )
        return records

    for event_index, event in enumerate(events):
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "todo_list" and action_context == "standard":
            if (
                event.get("type") not in {"item.started", "item.completed"}
                or set(item) != {"id", "type"}
            ):
                add(
                    "invalid",
                    "standard todo lifecycle has malformed shape",
                    event_index,
                )
            continue
        if event.get("type") == "item.completed" and item_type == "agent_message":
            value = item.get("text")
            if isinstance(value, str):
                add("text", value, event_index)
        elif event.get("type") == "item.started" and item_type == "command_execution":
            command = item.get("command")
            if not isinstance(command, str):
                add(
                    "invalid",
                    f"unrecognized {action_context} action: command_execution",
                    event_index,
                )
            elif is_codex_bootstrap(command, expected_plugin_root):
                continue
            elif is_read_only_inspection_command(
                command,
                expected_plugin_root,
                expected_project_root,
                require_files=False,
            ):
                continue
            else:
                add("mutation", command, event_index)
        elif event.get("type") == "item.completed" and item_type == "command_execution":
            command = item.get("command")
            if isinstance(command, str) and not is_codex_bootstrap(
                command, expected_plugin_root
            ) and is_read_only_inspection_command(
                command,
                expected_plugin_root,
                expected_project_root,
                require_files=False,
            ):
                exit_code = item.get("exit_code")
                completed_paths = inspection_command_paths(
                    command, expected_plugin_root, expected_project_root
                )
                if exit_code == 0 and completed_paths:
                    record_kind = (
                        "discovery"
                        if inspection_command_uses_glob(command)
                        else "inspection"
                    )
                    for path in completed_paths:
                        add(record_kind, path, event_index)
                elif exit_code is None:
                    add(
                        "invalid",
                        "Codex command lacks a completed inspection exit code",
                        event_index,
                    )
                elif exit_code == 0:
                    add(
                        "invalid",
                        "Codex inspection claimed success for an invalid project operand",
                        event_index,
                    )
        elif event.get("type") == "item.started" and item_type == "file_change":
            add("mutation", str(item_type), event_index)
        elif (
            event.get("type") == "item.started"
            and item_type not in {"agent_message", "reasoning"}
        ):
            add(
                "invalid",
                f"unrecognized {action_context} action: {item_type!r}",
                event_index,
            )
    return records


def has_valid_promotion_formatting(reason: str) -> bool:
    if not reason.endswith(".") or "?" in reason or "!" in reason:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in reason):
        return False
    if any(mark in reason for mark in ('"', "“", "”")):
        return False

    code_atoms = {
        "amount",
        "amountCents",
        "src/schema.js",
        "src/billing.js",
        "publicPaymentResponse",
    }
    object_atom = r"\{\s*amount\s*:\s*payment\s*\.\s*amount\s*\}"
    backtick_parts = reason.split("`")
    if len(backtick_parts) % 2 == 0:
        return False

    for index, part in enumerate(backtick_parts):
        if index % 2 == 1 and not (
            part in code_atoms or re.fullmatch(object_atom, part) is not None
        ):
            return False

    visible = "".join(
        part if index % 2 == 0 else "codeAtom"
        for index, part in enumerate(backtick_parts)
    )
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    stack: list[str] = []
    for character in visible:
        if character in pairs:
            stack.append(pairs[character])
        elif character in closing:
            if not stack or stack.pop() != character:
                return False
    return not stack


def neutralize_quoted_prose(reason: str) -> str:
    quote_spans = (
        r"(?<![\w/])'.+?'(?!\w)",
        r"‘.+?’",
        r"«.+?»",
    )
    for quote_span in quote_spans:
        reason = re.sub(quote_span, " quotedProse ", reason)
    return re.sub(r"\s+", " ", reason).strip()


def has_negated_required_relation(reason: str) -> bool:
    negated_relations = (
        r"\bsrc/schema\.js\b[^.;]*\b(?:never\s+defines?|"
        r"doesn['’]t\s+define)\b[^.;]*\bamount\b",
        r"\bdoes\s+not\s+consume\b",
        r"\bnever\s+(?:uses?|consumes?|consumed)\b",
        r"\b(?:isn['’]t|wasn['’]t)\s+(?:used|consumed)\s+by\s+"
        r"src/billing\.js\b",
        r"\bcannot\s+be\s+(?:used|consumed)\s+by\s+src/billing\.js\b",
        r"\b(?:would|will)\s+(?:never\s+|fail\s+to\s+)break\b",
    )
    return any(
        re.search(pattern, reason, re.IGNORECASE) is not None
        for pattern in negated_relations
    )


def has_affirmative_surface_relation(reason: str) -> bool:
    clauses = re.split(
        r"[.;,]+|\b(?:but|though|although|however)\b",
        reason,
        flags=re.IGNORECASE,
    )
    for clause in clauses:
        if re.search(r"\b(?:surface|response)\b", clause, re.IGNORECASE) is None:
            continue
        if re.search(
            r"\b(?:no|never|without|not(?!\s+only\b))\b",
            clause,
            re.IGNORECASE,
        ) is None:
            return True
    return False


def has_affirmative_public_api_relation(reason: str) -> bool:
    clauses = re.split(
        r"[.;,]+|\b(?:but|though|although|however)\b",
        reason,
        flags=re.IGNORECASE,
    )
    for clause in clauses:
        if not all(
            re.search(pattern, clause, re.IGNORECASE) is not None
            for pattern in (
                r"\bpublic\b",
                r"\b(?:billing|payments?)\b",
                r"\bapi\b",
            )
        ):
            continue
        if re.search(
            r"\b(?:no|never|without|not(?!\s+only\b))\b",
            clause,
            re.IGNORECASE,
        ) is None:
            return True
    return False


def has_affirmative_consequence_impact(consequence: str) -> bool:
    clauses = re.split(
        r"[.;,]+|\b(?:but|though|although|however)\b",
        consequence,
        flags=re.IGNORECASE,
    )
    signal_sets = (
        (r"\bcompatibility\b",),
        (r"\bresponse\b", r"\b(?:shape|contract|field)\b"),
        (r"\b(?:clients?|consumers?)\b",),
        (r"\bapi\b", r"\bchange\b"),
        (r"\bchange\b", r"\b(?:compatibility|contract)\b"),
    )
    for clause in clauses:
        if re.search(
            r"\b(?:no|never|without|not(?!\s+only\b))\b",
            clause,
            re.IGNORECASE,
        ) is not None:
            continue
        if any(
            all(
                re.search(pattern, clause, re.IGNORECASE) is not None
                for pattern in signals
            )
            for signals in signal_sets
        ):
            return True
    return False


def has_affirmative_breaking_consequence(consequence: str) -> bool:
    clauses = re.split(
        r"[.;,]+|\b(?:but|though|although|however)\b",
        consequence,
        flags=re.IGNORECASE,
    )
    for clause in clauses:
        if re.search(
            r"\b(?:no|never|without|not(?!\s+only\b))\b",
            clause,
            re.IGNORECASE,
        ) is not None:
            continue
        if re.search(r"\b(?:would|will)\b", clause, re.IGNORECASE) is None:
            continue
        if re.search(r"\bbreak(?:ing)?\b", clause, re.IGNORECASE) is not None:
            return True
        if (
            re.search(r"\bchange\b", clause, re.IGNORECASE) is not None
            and re.search(
                r"\b(?:compatibility|contract)\b",
                clause,
                re.IGNORECASE,
            )
            is not None
        ):
            return True
    return False


def has_structured_promotion_relation(reason: str) -> bool:
    if not has_valid_promotion_formatting(reason):
        return False

    normalized = re.sub(r"`+", "", reason)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = neutralize_quoted_prose(normalized)
    if re.search(
        r"\b(?:no|not|without|harmless|unrelated|merely|documentation|docs?|"
        r"examples?|quotations?|quotes?|false|nonpublic|private)\b|"
        r"\bbut\b[^.]*\b(?:actually\s+)?preserv(?:e|es|ed|ing)\s+"
        r"compatibility\b|"
        r"\b(?:claim|statement|relation)\s+is\s+incorrect\b",
        normalized,
        re.IGNORECASE,
    ):
        return False
    if has_negated_required_relation(normalized):
        return False
    if re.match(r"inspection\s+found\b", normalized, re.IGNORECASE) is None:
        return False

    rename = re.search(
        r"\brenaming\s+(?:"
        r"(?:the\s+)?amount(?:\s+field)?\s+to\s+amountcents|"
        r"it(?:\s+to\s+amountcents)?)\b",
        normalized,
        re.IGNORECASE,
    )
    if rename is None:
        return False

    evidence = normalized[: rename.start()]
    consequence = normalized[rename.end() :]
    source = re.search(
        r"\bsrc/schema\.js\b.*?\bdefines?\b.*?\bamount\b",
        evidence,
        re.IGNORECASE,
    )
    if source is None:
        return False

    after_source = evidence[source.end() :]
    consumed_by = re.search(
        r"\bconsumed\s+by\s+src/billing\.js"
        r"(?:'s\s+[A-Za-z_][A-Za-z0-9_]*)?\b",
        after_source,
        re.IGNORECASE,
    )
    billing_uses = re.search(
        r"\bsrc/billing\.js\b.*?\b(?:uses|consumes)\b.*?"
        r"\b(?:amount|it)\b",
        after_source,
        re.IGNORECASE,
    )
    consumer = consumed_by or billing_uses
    if consumer is None:
        return False

    public_relation_tail = after_source[consumer.end() :]
    if not has_affirmative_public_api_relation(public_relation_tail):
        return False
    surface_relation = f"{public_relation_tail} {consequence}"
    if re.search(r"\b(?:surface|response)\b", surface_relation, re.IGNORECASE):
        if not has_affirmative_surface_relation(surface_relation):
            return False

    if not has_affirmative_breaking_consequence(consequence):
        return False

    return has_affirmative_consequence_impact(consequence)


def validate_escalation_order(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
    expected_project_root: Path,
) -> None:
    inspected_project_paths: set[str] = set()
    promotion_seen = False
    pause_seen = False
    canonical_promotion_count = 0
    transition_count = 0
    transition_targets: list[str] = []
    prose_stream = MarkdownProseStream()
    awaiting_pause = False
    promotion_context_invalid = False
    for record in escalation_records(
        backend, events, expected_plugin_root, expected_project_root
    ):
        if record.kind == "invalid":
            raise ValidationError(record.value)
        if record.kind == "inspection":
            inspected_project_paths.add(record.value)
            continue
        if record.kind == "mutation":
            if not promotion_seen or not pause_seen:
                raise ValidationError(
                    "escalation mutation before strict promotion/approval pause"
                )
            continue

        for line in prose_stream.consume(record):
            if not line.text.strip():
                continue
            if line.qualifier:
                if promotion_seen:
                    promotion_context_invalid = True
                continue
            if line.contextual:
                continue

            transitions = list(WORKFLOW_TRANSITION.finditer(line.text))
            for transition in transitions:
                transition_count += 1
                transition_targets.append(transition.group("mode").lower())
                if (
                    transition.group("mode").lower() == "strict"
                    and not REQUIRED_ESCALATION_INSPECTIONS.issubset(
                        inspected_project_paths
                    )
                ):
                    raise ValidationError(
                        "strict promotion requires successful inspection of "
                        "src/schema.js and src/billing.js"
                    )

            match = PROMOTION.fullmatch(line.text)
            if match is not None:
                canonical_promotion_count += 1
                if canonical_promotion_count > 1:
                    raise ValidationError(
                        "escalation requires exactly one canonical promotion to strict"
                    )
                if match.group(1).lower() != "strict":
                    raise ValidationError("escalation requires promotion to strict")
                if not has_structured_promotion_relation(match.group(2)):
                    raise ValidationError(
                        "strict promotion lacks a closed structured promotion relation"
                    )
                if not REQUIRED_ESCALATION_INSPECTIONS.issubset(
                    inspected_project_paths
                ):
                    raise ValidationError(
                        "strict promotion requires successful inspection of "
                        "src/schema.js and src/billing.js"
                    )
                promotion_seen = True
                awaiting_pause = True
                continue

            if awaiting_pause:
                if has_relevant_pause(line.text):
                    pause_seen = True
                    awaiting_pause = False
                continue

    if not REQUIRED_ESCALATION_INSPECTIONS.issubset(inspected_project_paths):
        raise ValidationError(
            "escalation requires successful inspection of src/schema.js and "
            "src/billing.js after initial declaration"
        )
    if transition_count != 1:
        raise ValidationError("escalation requires exactly one workflow transition")
    if transition_targets != ["strict"]:
        raise ValidationError("escalation attempted automatic demotion")
    if canonical_promotion_count != 1 or not promotion_seen:
        raise ValidationError("escalation lacks exactly one canonical promotion to strict")
    if promotion_context_invalid:
        raise ValidationError("canonical promotion block contains non-workflow prose")
    if not pause_seen:
        raise ValidationError(
            "assistant-visible text lacks relevant clarification/approval pause"
        )


def has_standard_approval_pause(text: str) -> bool:
    return "?" in text or re.search(
        r"\blet\s+me\s+know\s+if\s+you(?:['’]d|\s+would)\s+like\s+"
        r"(?:any\s+)?changes?\s+before\s+I\s+(?:begin|start|implement)",
        text,
        re.IGNORECASE,
    ) is not None


def has_standard_inline_design(text: str) -> bool:
    words = re.findall(r"[A-Za-z0-9_./`-]+", text)
    if not 12 <= len(words) <= 180:
        return False

    concrete_action = (
        r"(?:add|build|calculate|change|compute|create|extend|implement|modify|"
        r"parse|read|refactor|return|update|wire|write)\w*"
    )
    negated_action = re.search(
        rf"\b(?:do\s+not|don't|will\s+not|won't|not\s+going\s+to|avoid)\b"
        rf"[^.;\n]{{0,180}}\b{concrete_action}\b",
        text,
        re.IGNORECASE,
    )
    negated_verification = re.search(
        r"\b(?:do\s+not|don't|will\s+not|won't|not\s+going\s+to|avoid)\b"
        r"[^.;\n]{0,180}\b(?:run|check|assert|compare|exercise|invoke|test|verify)\w*\b",
        text,
        re.IGNORECASE,
    )
    if negated_action or negated_verification:
        return False
    approach = re.search(
        rf"\b(?:approach|design|plan|implementation(?:\s+outline|\s+plan)?)\b"
        rf"[^\n]{{0,100}}\b{concrete_action}\b|"
        rf"\b(?:I|we)\s*(?:['’]ll|will)\s+{concrete_action}\b",
        text,
        re.IGNORECASE,
    )
    named_file = r"(?:`?[^\s`,;:]+/[A-Za-z0-9_.-]+`?|`?[A-Za-z0-9_-]+\.(?:js|ts|py|json|md|sh)`?)"
    named_component = (
        r"(?:CLI|command|parser|serializer|handler|service|module|component|"
        r"test\s+suite|tests?)"
    )
    affected = re.search(
        rf"\baffected\s+(?:files?|components?|surface)\b[^\n]{{0,140}}"
        rf"(?:{named_file}|\b{named_component}\b)|"
        rf"\b(?:add|implement|touch|change|modify|update|write)\w*\b"
        rf"[^\n]{{0,80}}{named_file}",
        text,
        re.IGNORECASE,
    )
    verification = re.search(
        r"\b(?:verification|test\s+strategy)\b[^\n]{0,140}"
        r"\b(?:run|check|assert|compare|exercise|invoke|verify)\w*\b"
        r"[^\n]{0,100}\b(?:npm\s+test|tests?|JSON|output|fixture|command|CLI)\b|"
        r"\b(?:I|we)\s*(?:['’]ll|will)\s+"
        r"(?:run|check|assert|compare|exercise|invoke|verify)\w*\b"
        r"[^\n]{0,100}\b(?:npm\s+test|tests?|JSON|output|fixture|command|CLI)\b|"
        r"(?:^|[;.]\s*)(?:run|check|assert|compare|exercise|invoke|verify)\w*\b"
        r"[^\n]{0,100}\b(?:npm\s+test|tests?|JSON|output|fixture|command|CLI)\b",
        text,
        re.IGNORECASE,
    )
    task_signal_families = (
        r"\b(?:CLI|command[- ]line|subcommand|command)\b|\bsrc/cli\.[A-Za-z0-9]+\b",
        r"\b(?:summar\w*|items?(?:\.json)?|count|total|prices?|aggregate\w*)\b",
        r"\b(?:tests?|specs?|npm\s+test)\b|\btest/[A-Za-z0-9_./-]+",
    )
    relevant_families = sum(
        re.search(pattern, text, re.IGNORECASE) is not None
        for pattern in task_signal_families
    )
    return bool(
        approach
        and affected
        and verification
        and relevant_families == len(task_signal_families)
    )


def validate_standard_inline_design_order(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
    expected_project_root: Path,
) -> None:
    inspection_seen = False
    pre_mutation_text: list[str] = []
    mutation_seen = False
    for record in escalation_records(
        backend,
        events,
        expected_plugin_root,
        expected_project_root,
        action_context="standard",
    ):
        if record.kind == "invalid":
            raise ValidationError(record.value)
        if record.kind in {"inspection", "discovery"}:
            inspection_seen = True
            continue
        if record.kind == "mutation":
            mutation_seen = True
            break
        if record.kind == "text":
            if inspection_seen:
                pre_mutation_text.append(record.value)

    if not inspection_seen:
        raise ValidationError(
            "standard inline design requires successful project inspection"
        )
    if not any(has_standard_inline_design(value) for value in pre_mutation_text):
        position = " before first mutation" if mutation_seen else " after inspection"
        raise ValidationError(
            "standard inline design lacks concrete approach, affected files/components, "
            f"and verification strategy{position}"
        )
    if has_standard_approval_pause("\n\n".join(pre_mutation_text)):
        raise ValidationError("standard inline design must not seek approval or pause")


def claude_brainstorming_skill_status(events: list[dict[str, Any]]) -> str:
    invocations: dict[str, str] = {}
    for event in events:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                tool_input = block.get("input")
                tool_id = block.get("id")
                if not (
                    block.get("name") == "Skill"
                    and isinstance(tool_input, dict)
                    and tool_input.get("skill") == "superpowers:brainstorming"
                    and isinstance(tool_id, str)
                    and tool_id
                ):
                    continue
                if tool_id in invocations:
                    invocations[tool_id] = "invalid"
                else:
                    invocations[tool_id] = "pending"
                continue
            if block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id")
            if not isinstance(tool_id, str) or tool_id not in invocations:
                continue
            if invocations[tool_id] != "pending":
                invocations[tool_id] = "invalid"
                continue
            successful_role = (
                event.get("type") == "user"
                and isinstance(message, dict)
                and message.get("role") == "user"
            )
            is_error = block.get("is_error", False)
            metadata_valid = True
            metadata_successful = True
            if "tool_use_result" in event:
                tool_use_result = event.get("tool_use_result")
                metadata_valid = (
                    isinstance(tool_use_result, dict)
                    and type(tool_use_result.get("success")) is bool
                )
                metadata_successful = (
                    metadata_valid and tool_use_result.get("success") is True
                )
            invocations[tool_id] = (
                "successful"
                if successful_role
                and type(is_error) is bool
                and is_error is False
                and metadata_valid
                and metadata_successful
                else "failed"
            )
    if not invocations:
        return "absent"
    if all(status == "successful" for status in invocations.values()):
        return "successful"
    return "failed"


def explicit_shell_payload(command: str) -> str | None:
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError:
        return None
    if (
        len(arguments) == 3
        and arguments[0] in {"/bin/zsh", "/bin/bash", "/bin/sh"}
        and arguments[1] == "-lc"
    ):
        return arguments[2]
    return command


def explicit_read_only_segment(
    segment: str,
    expected_project_root: Path,
    *,
    allow_stdin: bool = False,
) -> bool:
    try:
        arguments = shlex.split(segment, posix=True)
    except ValueError:
        return False
    if not arguments:
        return False
    if is_read_only_inspection_command(
        segment, None, expected_project_root, require_files=not allow_stdin
    ):
        return True
    if arguments[0] == "ls":
        operands = [argument for argument in arguments[1:] if not argument.startswith("-")]
        return bool(operands) and all(
            project_path(operand, expected_project_root) is not None
            for operand in operands
        )
    if arguments[0] == "grep":
        positional: list[str] = []
        for argument in arguments[1:]:
            if re.fullmatch(r"-[rnil]+", argument):
                continue
            if re.fullmatch(
                r"--(?:include|exclude|exclude-dir)=[A-Za-z0-9._*?/-]+",
                argument,
            ):
                continue
            if argument.startswith("-"):
                return False
            positional.append(argument)
        if not positional:
            return False
        operands = positional[1:]
        return (allow_stdin or bool(operands)) and all(
            project_path(operand, expected_project_root) is not None
            for operand in operands
        )
    if arguments[:2] == ["rg", "--files"]:
        options = arguments[2:]
        while options:
            if (
                len(options) < 2
                or options[0] != "-g"
                or re.fullmatch(r"!?[A-Za-z0-9._/-]+", options[1]) is None
            ):
                return False
            options = options[2:]
        return True
    if arguments[0] == "sed":
        if (
            len(arguments) < 3
            or arguments[1] != "-n"
            or re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", arguments[2])
            is None
        ):
            return False
        operands = arguments[3:]
        return (allow_stdin and not operands) or (
            bool(operands)
            and project_operand_paths(
                operands, expected_project_root, require_file=True
            )
            is not None
        )
    if arguments[0] == "git":
        git_arguments = arguments[1:]
        if len(git_arguments) >= 3 and git_arguments[0] == "-C":
            root = project_path(
                git_arguments[1], expected_project_root, require_directory=True
            )
            if root != expected_project_root.resolve(strict=True):
                return False
            git_arguments = git_arguments[2:]
        if not git_arguments:
            return False
        if git_arguments[0] == "log":
            return all(
                argument in {"--oneline", "--decorate"}
                or re.fullmatch(r"-\d+", argument) is not None
                for argument in git_arguments[1:]
            )
        return tuple(git_arguments) in {
            ("status", "--short"),
            ("status", "--porcelain"),
        }
    return False


def is_explicit_read_only_command(
    command: str,
    expected_plugin_root: Path | None,
    expected_project_root: Path,
) -> bool:
    if is_read_only_inspection_command(
        command, expected_plugin_root, expected_project_root
    ):
        return True
    arguments = split_read_command(command)
    if arguments and expected_plugin_root:
        operands: list[str] = []
        if arguments[0] == "cat" and not any(
            argument.startswith("-") for argument in arguments[1:]
        ):
            operands = arguments[1:]
        elif (
            arguments[0] == "sed"
            and len(arguments) >= 4
            and arguments[1] == "-n"
            and re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", arguments[2])
            is not None
            and not any(argument.startswith("-") for argument in arguments[3:])
        ):
            operands = arguments[3:]
        allowed_skill = (
            expected_plugin_root / "skills/brainstorming/SKILL.md"
        ).resolve(strict=False)
        if operands and all(
            Path(operand).is_absolute()
            and ".." not in Path(operand).parts
            and Path(operand).resolve(strict=False) == allowed_skill
            for operand in operands
        ):
            return True
    payload = explicit_shell_payload(command)
    if payload is None or any(
        token in payload for token in (";", "<", ">", "\n", "`", "$(")
    ):
        return False
    if "||" in payload or re.search(r"(?<!&)&(?!&)", payload):
        return False
    compound_groups = payload.split("&&")
    if any(not group.strip() for group in compound_groups):
        return False
    for group in compound_groups:
        pipeline = group.split("|")
        if any(not segment.strip() for segment in pipeline):
            return False
        if not all(
            explicit_read_only_segment(
                segment,
                expected_project_root,
                allow_stdin=index > 0,
            )
            for index, segment in enumerate(pipeline)
        ):
            return False
    return True


def validate_explicit_skill_actions(
    backend: str,
    events: list[dict[str, Any]],
    expected_plugin_root: Path | None,
    expected_project_root: Path,
) -> None:
    declared = False
    for event in events:
        if backend == "claude":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if event.get("type") == "assistant" and block.get("type") == "text":
                    value = block.get("text")
                    if isinstance(value, str) and DECLARATION.search(value):
                        declared = True
                    continue
                if not (
                    declared
                    and event.get("type") == "assistant"
                    and block.get("type") == "tool_use"
                ):
                    continue
                name = block.get("name")
                tool_input = block.get("input")
                if (
                    name == "Skill"
                    and isinstance(tool_input, dict)
                    and tool_input.get("skill") == "superpowers:brainstorming"
                ):
                    continue
                if name in {"Read", "Glob", "Grep"} and (
                    valid_claude_inspection(name, tool_input, expected_project_root)
                    or (name == "Read" and safe_claude_read_probe(
                        tool_input, expected_project_root
                    ))
                ):
                    continue
                if name == "Bash" and isinstance(tool_input, dict):
                    command = tool_input.get("command")
                    if isinstance(command, str) and is_explicit_read_only_command(
                        command, expected_plugin_root, expected_project_root
                    ):
                        continue
                raise ValidationError(
                    f"explicit-skill action is mutating or unrecognized: {name!r}"
                )
            continue

        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and DECLARATION.search(text):
                declared = True
            continue
        if not declared or item_type in {"reasoning", "todo_list"}:
            continue
        if item_type == "command_execution":
            command = item.get("command")
            if isinstance(command, str) and is_explicit_read_only_command(
                command, expected_plugin_root, expected_project_root
            ):
                continue
        raise ValidationError(
            f"explicit-skill action is mutating or unrecognized: {item_type!r}"
        )


def require_affirmative_brainstorming(
    text: str, *, structured_invocation_status: str = "visible-only"
) -> None:
    if structured_invocation_status in {"absent", "failed"}:
        raise ValidationError(
            "assistant-visible text lacks affirmative brainstorming skill use/invocation"
        )
    clauses = re.split(r"[.;\n]+|\bbut\b", text, flags=re.IGNORECASE)
    affirmative_patterns = (
        r"\b(?:I[’']m|we[’']re)\s+"
        r"(?:using|invoking|running)\s+(?:the\s+)?"
        r"`?superpowers:brainstorming`?\s+skill\b",
        r"\b(?:I|we)\s+(?:am|are|'m|'re|have|will|'ll)?\s*"
        r"(?:using|invoking|running|used|invoked|ran|use|invoke|run)\s+"
        r"(?:the\s+)?`?superpowers:brainstorming`?\s+skill\b",
        r"\b(?:I|we)\s+(?:am|are|'m|'re|have|will|'ll)?\s*"
        r"(?:using|invoking|running|used|invoked|ran|use|invoke|run)\s+"
        r"(?:the\s+)?brainstorming(?:\s+skill)?\b",
        r"\bbrainstorming\s+skill\s+(?:is|was)\s+"
        r"(?:active|loaded|invoked|running|used)\b",
        r"\bbrainstorming\s+skill\s+(?:now\s+)?guides\b",
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
    affirmative_seen = structured_invocation_status == "successful"
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
        r"(?:option|candidate)\s+\d+)\s*:\s*(?:\*\*)?"
        r"(?:`([A-Za-z_][A-Za-z0-9_-]*)`|"
        r"([A-Za-z_][A-Za-z0-9_-]*)(?=\s*(?:\*\*)?\s*(?:$|[:—–-])))",
        re.IGNORECASE,
    )
    ordered_backticked_label = re.compile(
        r"^\s*\d+[.)]\s+`([A-Za-z_][A-Za-z0-9_-]*)`\s*(?=$|[:—–-])"
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
            ordered_match = ordered_backticked_label.search(unit)
            label_match = label.search(unit)
            if ordered_match:
                identifier = ordered_match.group(1)
            elif label_match:
                identifier = label_match.group(1) or label_match.group(2)
            else:
                identifier = None
            if not identifier or negative_candidate(unit, identifier):
                continue
            candidates.add(identifier)
    if len(candidates) < 2:
        raise ValidationError(
            "assistant-visible brainstorming lacks at least two distinct positive options"
        )


def validate_case(
    case: str, text: str, *, structured_brainstorming_status: str = "visible-only"
) -> None:
    if case in {"lean", "standard"}:
        require_pattern(
            text,
            r"\b(evidence|verif\w*|tests?\s+pass)",
            "verification evidence",
        )
    elif case == "strict":
        require_strict_pause(text)
    elif case == "override":
        require_pattern(text, r"\b(warn|risk|security|authentication)", "high-risk override warning")
    elif case == "explicit-skill":
        require_affirmative_brainstorming(
            text, structured_invocation_status=structured_brainstorming_status
        )


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
        validate_escalation_order(
            backend,
            events,
            expected_plugin_root,
            transcript.parent / "project",
        )
    elif case == "standard":
        validate_standard_inline_design_order(
            backend,
            events,
            expected_plugin_root,
            transcript.parent / "project",
        )
    elif case == "explicit-skill":
        validate_explicit_skill_actions(
            backend,
            events,
            expected_plugin_root,
            transcript.parent / "project",
        )
    validate_case(
        case,
        visible,
        structured_brainstorming_status=(
            claude_brainstorming_skill_status(events)
            if backend == "claude"
            else "visible-only"
        ),
    )
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
