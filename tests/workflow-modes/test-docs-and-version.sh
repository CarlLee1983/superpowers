#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

DOC="$ROOT/docs/workflow-modes.md"
README="$ROOT/README.md"
RUNNER="$ROOT/tests/workflow-modes/run-static-tests.sh"
TARGET_VERSION="6.1.1-adaptive.1"

assert_file "$DOC" "workflow mode guide exists"
if [[ -f "$DOC" ]]; then
  assert_contains "$DOC" "chooses workflow depth from task risk" "guide documents risk-based selection"
  assert_contains "$DOC" "uncertainty, reversibility" "guide considers uncertainty and reversibility"
  assert_contains "$DOC" "blast radius, and external effects" "guide considers blast radius and external effects"
  assert_contains "$DOC" "does not use model names or a model allowlist" "guide rejects model allowlists"
  assert_contains "$DOC" "Every new task begins with one declaration" "guide requires one mode declaration"
  assert_contains "$DOC" "## Lean" "guide documents lean"
  assert_contains "$DOC" "## Standard" "guide documents standard"
  assert_contains "$DOC" "## Strict" "guide documents strict"
  for mode in lean standard strict; do
    assert_contains "$DOC" "Mode: $mode" "guide documents $mode override syntax"
  done
  assert_contains "$DOC" "Strict TDD is optional in lean mode" "guide makes lean TDD optional"
  assert_contains "$DOC" "Relevant verification remains mandatory" "guide keeps lean verification mandatory"
  assert_contains "$DOC" "proceeds without an approval pause" "guide keeps standard execution continuous"
  assert_contains "$DOC" "complete upstream Superpowers workflow" "guide preserves the upstream strict workflow"
  assert_contains "$DOC" "forced lean mode on high-risk work produces a warning but remains lean" "guide documents forced-lean warning behavior"
  assert_contains "$DOC" "may promote a mode when new risk appears" "guide documents risk promotion"
  assert_contains "$DOC" "never demotes it" "guide forbids automatic demotion"
  assert_contains "$DOC" "Fresh verification evidence is required in every mode" "guide documents the verification invariant"
  assert_contains "$DOC" "Explicit skill requests still run" "guide preserves explicit skill requests"
  assert_contains "$DOC" "Domain skills" "guide preserves domain skills"
  assert_contains "$DOC" "platform safety controls remain active" "guide preserves platform safety controls"
  assert_not_matches "$DOC" "upstream.*typo|typo.*upstream" "guide makes no unsupported upstream typo claim"
fi

assert_contains "$README" "## Adaptive workflow modes" "README introduces modes"
assert_contains "$README" "docs/workflow-modes.md" "README links to the workflow mode guide"
assert_contains "$README" "## The Strict Workflow" "README labels the complete workflow as strict"
assert_contains "$README" "The complete sequence is mandatory in strict mode" "README limits the complete sequence to strict mode"
assert_contains "$README" "standard" "README documents standard mode"
assert_contains "$README" "without an approval pause" "README documents continuous standard execution"
assert_contains "$README" "Relevant domain skills still apply" "README preserves domain skills"
assert_contains "$README" "Risk-proportionate TDD" "README documents risk-proportionate TDD"
assert_not_matches "$README" "upstream.*typo|typo.*upstream" "README makes no unsupported upstream typo claim"

if [[ -x "$RUNNER" ]]; then
  pass "static suite runner is executable"
else
  fail "static suite runner is executable"
fi
for test in \
  test-selector-contract.sh \
  test-planning-gates.sh \
  test-execution-gates.sh \
  test-evidence-gates.sh \
  test-docs-and-version.sh
do
  assert_contains "$RUNNER" "$test" "static suite includes $test"
done

expected_manifests=$'package.json\n.claude-plugin/plugin.json\n.cursor-plugin/plugin.json\n.codex-plugin/plugin.json\n.kimi-plugin/plugin.json\n.claude-plugin/marketplace.json\ngemini-extension.json'
actual_manifests="$(jq -r '.files[].path' "$ROOT/.version-bump.json")"
if [[ "$actual_manifests" == "$expected_manifests" ]]; then
  pass "version tooling declares every release manifest"
else
  fail "version tooling declares every release manifest"
fi

for manifest in \
  package.json \
  .claude-plugin/plugin.json \
  .cursor-plugin/plugin.json \
  .codex-plugin/plugin.json \
  .kimi-plugin/plugin.json \
  gemini-extension.json
do
  if jq -e --arg version "$TARGET_VERSION" '.version == $version' \
    "$ROOT/$manifest" >/dev/null; then
    pass "$manifest version is $TARGET_VERSION"
  else
    fail "$manifest version is $TARGET_VERSION"
  fi
done

if jq -e --arg version "$TARGET_VERSION" '.plugins[0].version == $version' \
  "$ROOT/.claude-plugin/marketplace.json" >/dev/null; then
  pass ".claude-plugin/marketplace.json version is $TARGET_VERSION"
else
  fail ".claude-plugin/marketplace.json version is $TARGET_VERSION"
fi

version_output="$("$ROOT/scripts/bump-version.sh" --check 2>&1)" || {
  printf '%s\n' "$version_output"
  fail "declared versions are synchronized"
}
if [[ "$version_output" == *"All declared files are in sync at $TARGET_VERSION"* ]]; then
  pass "declared versions are synchronized at $TARGET_VERSION"
else
  fail "declared versions are synchronized at $TARGET_VERSION"
fi

finish
