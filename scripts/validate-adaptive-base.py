#!/usr/bin/env python3
"""Validate the immutable upstream identity and Adaptive version consistency."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ADAPTIVE_VERSION = re.compile(r"^(\d+\.\d+\.\d+)-adaptive\.(\d+)$")
UPSTREAM_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
BASE_KEYS = {"repository", "tag", "commit"}


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def dotted_value(document: object, dotted_path: str) -> object:
    value = document
    for component in dotted_path.split("."):
        if component.isdigit():
            if not isinstance(value, list):
                raise KeyError(component)
            value = value[int(component)]
        else:
            if not isinstance(value, dict):
                raise KeyError(component)
            value = value[component]
    return value


def git_commit(root: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def validate(root: Path, release_tag: str | None) -> list[str]:
    errors: list[str] = []
    base_path = root / ".adaptive-base.json"
    version_config_path = root / ".version-bump.json"
    authority_path = root / ".codex-plugin" / "plugin.json"

    if not base_path.is_file():
        return [".adaptive-base.json is missing"]

    try:
        base = load_json(base_path)
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read .adaptive-base.json: {error}"]

    if not isinstance(base, dict):
        return [".adaptive-base.json must contain a JSON object"]

    actual_keys = set(base)
    if actual_keys != BASE_KEYS:
        missing = sorted(BASE_KEYS - actual_keys)
        extra = sorted(actual_keys - BASE_KEYS)
        if missing:
            errors.append(f".adaptive-base.json is missing keys: {', '.join(missing)}")
        if extra:
            errors.append(f".adaptive-base.json has unexpected keys: {', '.join(extra)}")

    repository = base.get("repository")
    tag = base.get("tag")
    commit = base.get("commit")
    if not isinstance(repository, str) or not repository:
        errors.append("upstream repository must be a non-empty string")
    if not isinstance(tag, str) or UPSTREAM_TAG.fullmatch(tag) is None:
        errors.append("upstream tag must be a stable tag in vX.Y.Z form")
    if not isinstance(commit, str) or FULL_COMMIT.fullmatch(commit) is None:
        errors.append("upstream commit must be a full lowercase 40-character SHA")

    try:
        authority = load_json(authority_path)
        adaptive_version = dotted_value(authority, "version")
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        errors.append(f"cannot read Adaptive version from .codex-plugin/plugin.json: {error}")
        adaptive_version = None

    version_match = (
        ADAPTIVE_VERSION.fullmatch(adaptive_version)
        if isinstance(adaptive_version, str)
        else None
    )
    if adaptive_version is not None and version_match is None:
        errors.append(
            f"Codex manifest version {adaptive_version!r} must use X.Y.Z-adaptive.N"
        )

    if version_match is not None and isinstance(tag, str):
        tag_match = UPSTREAM_TAG.fullmatch(tag)
        if tag_match is not None and version_match.group(1) != tag_match.group(1):
            errors.append(
                f"Adaptive version {adaptive_version} does not match upstream tag {tag}"
            )

    try:
        version_config = load_json(version_config_path)
        mappings = dotted_value(version_config, "files")
        if not isinstance(mappings, list):
            raise TypeError("files must be a list")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        errors.append(f"cannot read .version-bump.json: {error}")
        mappings = []

    for mapping in mappings:
        if not isinstance(mapping, dict):
            errors.append(".version-bump.json contains a non-object file mapping")
            continue
        relative_path = mapping.get("path")
        field = mapping.get("field")
        if not isinstance(relative_path, str) or not isinstance(field, str):
            errors.append(".version-bump.json file mappings require string path and field")
            continue
        manifest_path = root / relative_path
        if not manifest_path.is_file():
            errors.append(f"declared manifest is missing: {relative_path}")
            continue
        try:
            manifest = load_json(manifest_path)
            manifest_version = dotted_value(manifest, field)
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            errors.append(f"cannot read {relative_path} ({field}): {error}")
            continue
        if adaptive_version is not None and manifest_version != adaptive_version:
            errors.append(
                f"{relative_path} ({field}) is {manifest_version}; expected {adaptive_version}"
            )

    if isinstance(tag, str) and UPSTREAM_TAG.fullmatch(tag) is not None:
        try:
            resolved_tag = git_commit(root, f"refs/tags/{tag}")
        except subprocess.CalledProcessError:
            errors.append(f"upstream tag is unavailable locally: {tag}")
        else:
            if isinstance(commit, str) and resolved_tag != commit:
                errors.append(f"{tag} resolves to {resolved_tag}; metadata records {commit}")

    if release_tag is not None:
        try:
            resolved_release = git_commit(root, f"refs/tags/{release_tag}")
        except subprocess.CalledProcessError:
            errors.append(f"release tag is unavailable locally: {release_tag}")
        else:
            try:
                head = git_commit(root, "HEAD")
            except subprocess.CalledProcessError:
                errors.append("HEAD does not resolve to a commit")
            else:
                if resolved_release != head:
                    errors.append(
                        f"release tag {release_tag} does not resolve to HEAD "
                        f"({resolved_release} != {head})"
                    )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the script's parent repository)",
    )
    parser.add_argument("--release-tag", help="require this tag to resolve to HEAD")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()

    errors = validate(root, arguments.release_tag)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    base = load_json(root / ".adaptive-base.json")
    manifest = load_json(root / ".codex-plugin" / "plugin.json")
    print(
        f"Adaptive {dotted_value(manifest, 'version')} is based on "
        f"{dotted_value(base, 'tag')} ({dotted_value(base, 'commit')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
