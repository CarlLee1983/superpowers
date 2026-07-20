#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

DOC="$ROOT/docs/workflow-modes.md"
README="$ROOT/README.md"
RUNNER="$ROOT/tests/workflow-modes/run-static-tests.sh"
TARGET_VERSION="6.1.1-adaptive.1"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

section_text() {
  local file="$1" heading="$2"
  awk -v heading="$heading" '
    $0 == heading { in_section = 1; next }
    in_section && /^## / { exit }
    in_section { print }
  ' "$file"
}

guide_preamble_text() {
  local file="$1"
  awk '/^## Lean$/ { exit } { print }' "$file"
}

normalize_contract_text() {
  awk '
    {
      gsub(/[[:space:]]+/, " ")
      sub(/^ /, "")
      sub(/ $/, "")
      if (length) {
        if (out != "") out = out " "
        out = out $0
      }
    }
    END { print out }
  '
}

guide_contract_valid() {
  local file="$1"
  local headings preamble lean standard strict guarantees
  local expected_preamble expected_lean expected_standard expected_strict
  local expected_guarantees

  [[ -f "$file" ]] || return 1
  headings="$(rg '^## ' "$file")"
  [[ "$headings" == $'## Lean\n## Standard\n## Strict\n## Guarantees' ]] || return 1

  expected_preamble='# Adaptive workflow modes Superpowers chooses workflow depth from task risk, uncertainty, reversibility, blast radius, and external effects. It does not use model names or a model allowlist. Every new task begins with one declaration: `Mode: lean — localized, reversible change with direct verification.` Use `Mode: lean`, `Mode: standard`, or `Mode: strict` in your request to override automatic selection.'
  expected_lean='Lean mode is for clear, localized, reversible work. The agent inspects, changes, runs the most relevant verification, reviews the diff, and reports evidence. Written specs, worktrees, subagents, and independent review are optional. Strict TDD is optional in lean mode. Relevant verification remains mandatory.'
  expected_standard='Standard mode is for bounded multi-component work. The agent gives a short inline design and execution outline, then proceeds without an approval pause. It uses test-first development, isolation, subagents, and independent review only when they materially control risk.'
  expected_strict='Strict mode is for security, payments, production data, migrations, irreversible operations, breaking APIs, broad architecture, or material ambiguity. It preserves the complete upstream Superpowers workflow.'
  expected_guarantees='- Fresh verification evidence is required in every mode. - Explicit skill requests still run. - Domain skills remain active. - Host and platform safety controls remain active. - The agent may promote a mode when new risk appears, but never demotes it automatically within a task. - A forced lean mode on high-risk work produces a warning but remains lean.'

  preamble="$(guide_preamble_text "$file" | normalize_contract_text)"
  lean="$(section_text "$file" "## Lean" | normalize_contract_text)"
  standard="$(section_text "$file" "## Standard" | normalize_contract_text)"
  strict="$(section_text "$file" "## Strict" | normalize_contract_text)"
  guarantees="$(section_text "$file" "## Guarantees" | normalize_contract_text)"

  [[ "$preamble" == "$expected_preamble" ]] || return 1
  [[ "$lean" == "$expected_lean" ]] || return 1
  [[ "$standard" == "$expected_standard" ]] || return 1
  [[ "$strict" == "$expected_strict" ]] || return 1
  [[ "$guarantees" == "$expected_guarantees" ]] || return 1
}

insert_before_next_section() {
  local source="$1" destination="$2" heading="$3" insertion="$4"
  awk -v heading="$heading" -v insertion="$insertion" '
    $0 == heading { in_section = 1 }
    in_section && $0 != heading && /^## / && ! inserted {
      print insertion
      inserted = 1
    }
    { print }
    END {
      if (in_section && ! inserted) print insertion
    }
  ' "$source" >"$destination"
}

assert_guide_mutation_rejected() {
  local name="$1" heading="$2" insertion="$3"
  local mutated="$TEST_TMP/$name.md"

  insert_before_next_section "$DOC" "$mutated" "$heading" "$insertion"
  if guide_contract_valid "$mutated"; then
    fail "guide contract rejects $name contradiction"
  else
    pass "guide contract rejects $name contradiction"
  fi
}

runner_contract_valid() {
  local runner="$1"
  local case_dir fixture runner_home log expected actual test

  case_dir="$(mktemp -d "$TEST_TMP/runner.XXXXXX")"
  fixture="$case_dir/fixture"
  runner_home="$case_dir/runner-home"
  log="$case_dir/calls.log"
  mkdir -p "$fixture" "$runner_home"
  cp "$runner" "$runner_home/run-static-tests.sh"
  chmod +x "$runner_home/run-static-tests.sh"

  expected=""
  for test in \
    test-selector-contract.sh \
    test-planning-gates.sh \
    test-execution-gates.sh \
    test-evidence-gates.sh \
    test-docs-and-version.sh
  do
    printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' \
      'printf '\''%s\n'\'' "$(basename "$0")" >>"$WORKFLOW_MODES_RUNNER_LOG"' \
      >"$fixture/$test"
    chmod +x "$fixture/$test"
    expected+="$test"$'\n'
  done
  expected="${expected%$'\n'}"

  if WORKFLOW_MODES_TEST_DIR="$fixture" WORKFLOW_MODES_RUNNER_LOG="$log" \
    "$runner_home/run-static-tests.sh" >/dev/null 2>&1 && [[ -f "$log" ]]; then
    actual="$(<"$log")"
    [[ "$actual" == "$expected" ]]
  else
    return 1
  fi
}

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
  if guide_contract_valid "$DOC"; then
    pass "guide sections satisfy the invariant contract"
  else
    fail "guide sections satisfy the invariant contract"
  fi
  assert_guide_mutation_rejected "lean-omits-verification" "## Lean" "Lean can omit relevant verification."
  assert_guide_mutation_rejected "lean-controls-do-not-apply" "## Lean" "Platform safety controls do not apply in Lean."
  assert_guide_mutation_rejected "standard-pauses-for-approval" "## Standard" "Standard pauses for approval before execution."
  assert_guide_mutation_rejected "strict-partial-upstream" "## Strict" "Strict follows only part of the upstream Superpowers workflow."
  assert_guide_mutation_rejected "model-capability-name-routing" "## Guarantees" "Mode selection routes by model capability and name."
  assert_guide_mutation_rejected "automatic-mode-lowering" "## Guarantees" "The agent may lower the mode automatically."
  wording_mutation="$TEST_TMP/legitimate-wording-change.md"
  sed 's/Relevant verification remains mandatory/Relevant verification is still mandatory/' \
    "$DOC" >"$wording_mutation"
  if guide_contract_valid "$wording_mutation"; then
    fail "contract wording changes require a canonical expectation update"
  else
    pass "contract wording changes require a canonical expectation update"
  fi
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
how_it_works="$(section_text "$README" "## How it works")"
[[ "$how_it_works" == *"Every task starts with workflow-mode selection"* ]] \
  && pass "README starts every task with mode selection" \
  || fail "README starts every task with mode selection"
[[ "$how_it_works" == *"Lean"* && "$how_it_works" == *"focused verification"* ]] \
  && pass "README How it works summarizes lean" \
  || fail "README How it works summarizes lean"
[[ "$how_it_works" == *"Standard"* && "$how_it_works" == *"without an approval pause"* ]] \
  && pass "README How it works summarizes standard" \
  || fail "README How it works summarizes standard"
[[ "$how_it_works" == *"Strict"* && "$how_it_works" == *"full questions, design, plan, TDD, and subagent workflow"* ]] \
  && pass "README How it works scopes the full workflow to strict" \
  || fail "README How it works scopes the full workflow to strict"
if [[ "$how_it_works" == *"As soon as it sees that you're building"* ||
  "$how_it_works" == *"Once it's teased a spec"* ||
  "$how_it_works" == *"After you've signed off"* ||
  "$how_it_works" == *'once you say "go"'* ]]; then
  fail "README How it works has no universal strict-workflow claims"
else
  pass "README How it works has no universal strict-workflow claims"
fi

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
if runner_contract_valid "$RUNNER"; then
  pass "static runner executes each contract exactly once in order"
else
  fail "static runner executes each contract exactly once in order"
fi
runner_without_execution="$TEST_TMP/run-static-tests-without-execution.sh"
sed '/"$TEST_DIR\/$test"/d' "$RUNNER" >"$runner_without_execution"
chmod +x "$runner_without_execution"
if runner_contract_valid "$runner_without_execution"; then
  fail "runner behavior rejects a missing execution line"
else
  pass "runner behavior rejects a missing execution line"
fi

expected_version_mappings=$'package.json\tversion\n.claude-plugin/plugin.json\tversion\n.cursor-plugin/plugin.json\tversion\n.codex-plugin/plugin.json\tversion\n.kimi-plugin/plugin.json\tversion\n.claude-plugin/marketplace.json\tplugins.0.version\ngemini-extension.json\tversion'
actual_version_mappings="$(jq -r '.files[] | "\(.path)\t\(.field)"' "$ROOT/.version-bump.json")"
if [[ "$actual_version_mappings" == "$expected_version_mappings" ]]; then
  pass "version tooling declares every exact path and field mapping"
else
  fail "version tooling declares every exact path and field mapping"
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
