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
    r"(?i)^Promoting\s+to\s+(lean|standard|strict)\s+[—-]\s*([^\n]+)$"
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
    for argument in arguments:
        if re.search(r"[?\[\]{}~$]", argument):
            return None
        if "*" in argument:
            expanded = safe_project_glob_paths(argument, expected_project_root)
            if expanded is None:
                return None
            if not expanded:
                return ()
            paths.extend(expanded)
            continue
        resolved = project_path(
            argument,
            expected_project_root,
            require_file=require_file,
        )
        if resolved is None:
            return None
        paths.append(resolved.relative_to(root).as_posix())
    return tuple(paths)


def inspection_command_paths(
    command: str,
    expected_root: Path | None,
    expected_project_root: Path,
    *,
    require_files: bool = True,
) -> tuple[str, ...] | None:
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
                    if name in {"Read", "Glob", "Grep"}:
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
                            tool_uses[tool_id] = ("inspection", paths)
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
                            f"unrecognized escalation action: {name!r}",
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
                if tool_kind in {"inspection", "inspection_probe"}:
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
                    else:
                        add(
                            "invalid",
                            f"inspection probe claimed success for missing path {tool_id!r}",
                            event_index,
                        )
        missing_results = [
            tool_id
            for tool_id, (kind, _) in tool_uses.items()
            if kind in {"inspection", "inspection_probe"}
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
        if event.get("type") == "item.completed" and item_type == "agent_message":
            value = item.get("text")
            if isinstance(value, str):
                add("text", value, event_index)
        elif event.get("type") == "item.started" and item_type == "command_execution":
            command = item.get("command")
            if not isinstance(command, str):
                add(
                    "invalid",
                    "unrecognized escalation action: command_execution",
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
                    for path in completed_paths:
                        add("inspection", path, event_index)
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
                f"unrecognized escalation action: {item_type!r}",
                event_index,
            )
    return records


def has_structured_promotion_relation(reason: str) -> bool:
    normalized = re.sub(r"`+", "", reason)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    identifier = r"[A-Za-z_$][\w$]*"
    observed_alias_relation = (
        r"\(\s*publicPaymentResponse\s+returns\s+"
        r"\{\s*amount\s*:\s*payment\s*\.\s*amount\s*\}\s*\)"
    )
    source = r"src/schema\.js\s+defines\s+(?:the\s+)?amount(?:\s+field)?"
    consumer = (
        rf"(?:,?\s+(?:is\s+)?(?:used|consumed)\s+by\s+"
        rf"(?:(?:{identifier})\s+in\s+)?src/billing\.js"
        rf"(?:'s\s+{identifier}|\s+{observed_alias_relation})?|"
        rf"\s+(?:and\s+)?src/billing\.js"
        rf"(?:'s\s+{identifier}|\s+{observed_alias_relation})?\s+"
        rf"(?:uses|consumes)\s+(?:the\s+)?(?:amount|it)(?:\s+field)?)"
    )
    public_surface = (
        r"(?:as\s+part\s+of|in)\s+(?:(?:the|a)\s+)?(?:production\s+)?public\s+"
        r"(?:billing|payments?)(?:\s+(?:billing|payments?))?\s+api"
        r"(?:\s+(?:billing|payments?|response|surface|compatibility))*"
    )
    evidence = rf"inspection\s+found\s+{source}{consumer}\s+{public_surface}"
    rename = (
        r"renaming\s+(?:the\s+)?(?:amount|it)(?:\s+field)?"
        r"(?:\s+to\s+amountcents)?"
    )
    breaking_object = (
        r"(?:compatibility|(?:the\s+)?response\s+shape\s+for\s+external\s+"
        r"billing\s+api\s+clients?|(?:the\s+)?(?:public\s+|external\s+)?"
        r"(?:(?:billing|payments?)\s+)?api(?:'s)?\s+"
        r"(?:change|response(?:\s+shape)?|compatibility(?:\s+change)?|contract)"
        r"(?:\s+for\s+(?:external|existing)\s+(?:clients?|consumers?))?)"
    )
    breaking_change = (
        r"(?:a\s+)?breaking\s+"
        r"(?:(?:public|external|billing|payments?)\s+)*api\s+"
        r"(?:change|response(?:\s+shape)?|compatibility(?:\s+change)?|contract)"
    )
    consequence = (
        rf"(?:would|will)\s+(?:break\s+{breaking_object}|"
        rf"(?:create|cause)\s+{breaking_change})"
    )
    return re.fullmatch(
        rf"{evidence}\s*;\s*{rename}\s+{consequence}\.?",
        normalized,
        re.IGNORECASE,
    ) is not None


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
    promotion_record_order: int | None = None
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
                promotion_record_order = line.record_order
                awaiting_pause = True
                continue

            if awaiting_pause:
                if has_relevant_pause(line.text):
                    pause_seen = True
                    awaiting_pause = False
                    continue
                promotion_context_invalid = True
                continue
            if line.record_order == promotion_record_order:
                promotion_context_invalid = True

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
        validate_escalation_order(
            backend,
            events,
            expected_plugin_root,
            transcript.parent / "project",
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
