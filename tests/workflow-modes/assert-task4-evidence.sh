#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

EVIDENCE_ROOT="${1:-/tmp/superpowers-mode-evals/task-4}"
CASE="${2:-all}"
NORMALIZED=""

normalize_transcript() {
  local transcript="$1" destination="$2"
  jq -s '
    def outer_error($event):
      if (($event.tool_use_result? // null) | type) == "string"
      then ($event.tool_use_result | startswith("Error:"))
      elif (($event.tool_use_result? // null) | type) == "object"
      then ($event.tool_use_result.is_error? // false)
      else false
      end;
    def outer_interrupted($event):
      if (($event.tool_use_result? // null) | type) == "object"
      then ($event.tool_use_result.interrupted? // false)
      else false
      end;
    [
      to_entries[] as $entry
      | $entry.key as $order
      | $entry.value as $event
      | if $event.type == "assistant"
        then $event.message.content[]?
          | if .type == "tool_use"
            then {
              order: $order, kind: "call", id: .id, name: .name,
              command: (.input.command? // ""),
              description: (.input.description? // ""),
              skill: (.input.skill? // ""),
              file_path: (.input.file_path? // ""),
              old_string: (.input.old_string? // ""),
              new_string: (.input.new_string? // ""),
              content: (.input.content? // "")
            }
            elif .type == "text"
            then {order: $order, kind: "text", content: .text}
            else empty end
        elif $event.type == "user"
        then $event.message.content[]?
          | select(.type == "tool_result")
          | {
              order: $order, kind: "result", id: .tool_use_id,
              content: (.content | tostring),
              is_error: (.is_error? // outer_error($event)),
              interrupted: outer_interrupted($event)
            }
        else empty end
    ]
  ' "$transcript" > "$destination"
}

jq_assert() {
  local label="$1" filter="$2"
  if jq -e "$filter" "$NORMALIZED" >/dev/null; then pass "$label"; else fail "$label"; fi
}

commands_are_unmasked() {
  local file="$1"
  jq -e '
    all(
      .[] | select(.kind == "call" and .name == "Bash");
      (.command
        | test(";[[:space:]]*(echo|printf|true|exit)([[:space:]]|$)|\\|\\||[[:space:]]\\|[[:space:]]")
        | not)
    )
  ' "$file" >/dev/null
}

assert_common() {
  local label="$1" expected_skill="$2"
  jq_assert "$label invokes the routed skill" \
    "any(.[];
      .kind == \"call\" and .name == \"Skill\"
      and .skill == \"$expected_skill\"
    )"
  jq_assert "$label does not invoke the workflow-mode selector" \
    'all(.[]; .kind != "call" or .skill != "superpowers:selecting-workflow-mode")'
  if commands_are_unmasked "$NORMALIZED"; then
    pass "$label uses standalone unmasked shell commands"
  else
    fail "$label uses standalone unmasked shell commands"
  fi
}

assert_call_result() {
  local label="$1" command_fragment="$2" expected_error="$3" output_fragment="$4"
  jq_assert "$label" "
    ([.[] | select(
      .kind == \"call\" and .name == \"Bash\"
      and (.command | contains(\"$command_fragment\"))
    )] | first) as \$call
    | \$call != null
      and any(.[];
        .kind == \"result\" and .id == \$call.id and .order >= \$call.order
        and .is_error == $expected_error and .interrupted == false
        and (.content | contains(\"$output_fragment\"))
      )
  "
}

load_case() {
  local label="$1" transcript="$2"
  if [[ ! -f "$transcript" ]]; then fail "$label transcript exists"; return 1; fi
  pass "$label transcript exists"
  NORMALIZED="$(mktemp)"
  normalize_transcript "$transcript" "$NORMALIZED"
}

assert_general_edit() {
  local label="$1" expected_old="$2" expected_new="$3"
  jq_assert "$label uses a general source fix" "
    any(.[];
      .kind == \"call\" and .name == \"Edit\"
      and (.old_string | contains(\"$expected_old\"))
      and (.new_string | contains(\"$expected_new\"))
      and (.new_string | test(\"if[[:space:]]*\\\\(|===|==\") | not)
    )
  "
}

validate_lean_debug() {
  local label="lean debugging"
  load_case "$label" "$EVIDENCE_ROOT/systematic-debugging/green/transcript.jsonl" || return
  assert_common "$label" "superpowers:systematic-debugging"
  jq_assert "$label has exactly one expected failing result" \
    '[.[] | select(.kind == "result" and .is_error == true)] | length == 1'
  assert_call_result "$label reproduces the symptom with raw exit 1" \
    "import { double }" true "expected 6, got 7"
  jq_assert "$label gathers root-cause history before editing" '
    ([.[] | select(
      .kind == "result"
      and (.content | contains("regression: add offset to double result"))
      and (.content | contains("+  return value * 2 + 1;"))
    )] | first) as $evidence
    | ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | $evidence != null and $edit != null and $evidence.order < $edit.order
  '
  assert_general_edit "$label" "return value * 2 + 1;" "return value * 2;"
  jq_assert "$label reruns the regression after the edit with raw success" '
    ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | ([.[] | select(
      .kind == "call" and .name == "Bash" and .order > $edit.order
      and (.command | contains("import { double }"))
    )] | first) as $check
    | $check != null and any(.[];
      .kind == "result" and .id == $check.id and .is_error == false
      and (.content | test("Exit code [1-9]") | not)
    )
  '
  jq_assert "$label inspects a post-edit general diff" '
    ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "git diff")] | first) as $diff
    | $edit != null and $diff != null and $diff.order > $edit.order
      and any(.[];
        .kind == "result" and .id == $diff.id and .is_error == false
        and (.content | contains("-  return value * 2 + 1;"))
        and (.content | contains("+  return value * 2;"))
      )
  '
  jq_assert "$label avoids strict-only TDD" \
    'all(.[]; .kind != "call" or .skill != "superpowers:test-driven-development")'
}

validate_standard_debug() {
  local label="standard debugging"
  load_case "$label" "$EVIDENCE_ROOT/systematic-debugging/green/standard-positive/transcript.jsonl" || return
  assert_common "$label" "superpowers:systematic-debugging"
  jq_assert "$label has exactly one expected failing result" \
    '[.[] | select(.kind == "result" and .is_error == true)] | length == 1'
  assert_call_result "$label reproduces the symptom with raw exit 1" \
    "import { triple }" true "expected 12, got 8"
  jq_assert "$label tests an explicit evidence-backed hypothesis before editing" '
    ([.[] | select(
      .kind == "result"
      and (.content | contains("regression: use wrong triple multiplier"))
      and (.content | contains("-  return value * 3;"))
      and (.content | contains("+  return value * 2;"))
    )] | first) as $evidence
    | ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | $evidence != null and $edit != null and $evidence.order < $edit.order
      and any(.[]; .kind == "text" and (.content | test("假設|hypothesis"; "i")))
  '
  assert_general_edit "$label" "return value * 2;" "return value * 3;"
  jq_assert "$label reruns the regression after the edit with raw success" '
    ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | ([.[] | select(
      .kind == "call" and .name == "Bash" and .order > $edit.order
      and (.command | contains("import { triple }"))
    )] | first) as $check
    | $check != null and any(.[];
      .kind == "result" and .id == $check.id and .is_error == false
      and (.content | test("Exit code [1-9]") | not)
    )
  '
  jq_assert "$label inspects a post-edit general diff" '
    ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "git diff")] | first) as $diff
    | $edit != null and $diff != null and $diff.order > $edit.order
      and any(.[];
        .kind == "result" and .id == $diff.id
        and (.content | contains("-  return value * 2;"))
        and (.content | contains("+  return value * 3;"))
      )
  '
  jq_assert "$label avoids strict-only TDD" \
    'all(.[]; .kind != "call" or .skill != "superpowers:test-driven-development")'
}

validate_strict_debug() {
  local label="strict debugging"
  load_case "$label" "$EVIDENCE_ROOT/systematic-debugging/green/strict-positive/transcript.jsonl" || return
  assert_common "$label" "superpowers:systematic-debugging"
  jq_assert "$label has only the expected reproduction and RED failures" \
    '[.[] | select(.kind == "result" and .is_error == true)] | length == 2'
  assert_call_result "$label reproduces the original symptom with raw exit 1" \
    "import { quadruple }" true "expected 12, got 9"
  jq_assert "$label completes Phase 1 root-cause evidence before editing" '
    ([.[] | select(
      .kind == "result"
      and (.content | contains("regression: use triple multiplier in quadruple"))
      and (.content | contains("-  return value * 4;"))
      and (.content | contains("+  return value * 3;"))
    )] | first) as $root
    | ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | $root != null and $edit != null and $root.order < $edit.order
  '
  jq_assert "$label compares a working pattern before editing" '
    ([.[] | select(.kind == "result" and (.content | contains("return value * 2;")))] | first) as $pattern
    | ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | $pattern != null and $edit != null and $pattern.order < $edit.order
  '
  jq_assert "$label tests the multiplier hypothesis before editing" '
    ([.[] | select(.kind == "result" and (.content | contains("hypothesis confirmed: value * 4 yields 12")))] | first) as $hypothesis
    | ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | $hypothesis != null and $edit != null and $hypothesis.order < $edit.order
  '
  jq_assert "$label invokes TDD before writing the permanent test" '
    ([.[] | select(.kind == "call" and .name == "Skill" and .skill == "superpowers:test-driven-development")] | first) as $tdd
    | ([.[] | select(.kind == "call" and .name == "Write" and (.file_path | endswith("/test/quadruple.test.js")))] | first) as $write
    | $tdd != null and $write != null and $tdd.order < $write.order
  '
  jq_assert "$label observes permanent-test RED before source edit" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test")] | first) as $red
    | ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | $red != null and $edit != null and $red.order < $edit.order
      and any(.[]; .kind == "result" and .id == $red.id and .is_error == true and (.content | contains("9 !== 12")))
  '
  assert_general_edit "$label" "return value * 3;" "return value * 4;"
  jq_assert "$label observes GREEN after the source edit" '
    ([.[] | select(.kind == "call" and .name == "Edit")] | first) as $edit
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test" and .order > $edit.order)] | first) as $green
    | $green != null and any(.[];
      .kind == "result" and .id == $green.id and .is_error == false
      and (.content | contains("quadruple tests passed"))
    )
  '
  jq_assert "$label reruns the original regression after GREEN" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test")] | last) as $green
    | ([.[] | select(
      .kind == "call" and .name == "Bash" and .order > $green.order
      and (.command | contains("import { quadruple }"))
    )] | first) as $regression
    | $regression != null and any(.[];
      .kind == "result" and .id == $regression.id and .is_error == false
      and (.content | test("Exit code [1-9]") | not)
    )
  '
  jq_assert "$label inspects a post-GREEN general diff" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test")] | last) as $green
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "git diff")] | first) as $diff
    | $diff != null and $diff.order > $green.order
      and any(.[];
        .kind == "result" and .id == $diff.id
        and (.content | contains("-  return value * 3;"))
        and (.content | contains("+  return value * 4;"))
      )
  '
  jq_assert "$label reports all four completed phases" '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | all(["Phase 1", "Phase 2", "Phase 3", "Phase 4"][]; $text | contains(.))
  '
}

validate_lean_verify() {
  local label="lean verification"
  load_case "$label" "$EVIDENCE_ROOT/verification-before-completion/green/transcript.jsonl" || return
  assert_common "$label" "superpowers:verification-before-completion"
  jq_assert "$label has no command errors" 'all(.[]; .kind != "result" or .is_error == false)'
  jq_assert "$label runs exactly the focused check and diff" '
    [.[] | select(.kind == "call" and .name == "Bash") | .command]
    | sort == ["./test/label.test.sh", "git diff"]
  '
  assert_call_result "$label gets fresh focused proof" \
    "./test/label.test.sh" false "focused failures: 0"
  jq_assert "$label inspects the exact source diff" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "git diff")] | first) as $diff
    | $diff != null and any(.[];
      .kind == "result" and .id == $diff.id
      and (.content | contains("-export const label = \"Ready\";"))
      and (.content | contains("+export const label = \"Ready!\";"))
    )
  '
  jq_assert "$label scopes the final claim narrowly" '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | ($text | test("narrow claim"; "i"))
      and ($text | test("no broader claim|did not run.*verify-all"; "i"))
  '
}

validate_standard_verify() {
  local label="standard verification"
  load_case "$label" "$EVIDENCE_ROOT/verification-before-completion/green/standard-positive/transcript.jsonl" || return
  assert_common "$label" "superpowers:verification-before-completion"
  jq_assert "$label has no command errors" 'all(.[]; .kind != "result" or .is_error == false)'
  jq_assert "$label runs relevant, static, integrated, and diff commands only" '
    [.[] | select(.kind == "call" and .name == "Bash") | .command]
    | sort == ["./test/integration.sh", "./test/label.test.sh", "./test/static.sh", "git diff"]
  '
  assert_call_result "$label gets fresh relevant-test proof" \
    "./test/label.test.sh" false "focused failures: 0"
  assert_call_result "$label gets fresh static proof" \
    "./test/static.sh" false "static failures: 0"
  assert_call_result "$label gets fresh integrated proof" \
    "./test/integration.sh" false "integration failures: 0"
  jq_assert "$label does not claim strict complete-suite coverage" '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | ($text | test("未執行.*verify-all|did not run.*verify-all"; "i"))
  '
}

strict_labels_pass() {
  local file="$1"
  jq -e '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | all(
        [
          "SPEC label exact", "SPEC syntax valid", "SPEC integrated import",
          "PLAN complete suite", "PLAN output and exit status",
          "PLAN current diff", "PLAN requirements checked"
        ][] as $label
        | $text
        | contains($label + " — PASS")
      )
  ' "$file" >/dev/null
}

validate_strict_verify() {
  local label="strict verification"
  load_case "$label" "$EVIDENCE_ROOT/verification-before-completion/green/strict-positive/transcript.jsonl" || return
  assert_common "$label" "superpowers:verification-before-completion"
  jq_assert "$label has no command errors" 'all(.[]; .kind != "result" or .is_error == false)'
  jq_assert "$label reads the written spec and plan" '
    any(.[]; .kind == "call" and .name == "Read" and (.file_path | endswith("/SPEC.md")))
    and any(.[]; .kind == "call" and .name == "Read" and (.file_path | endswith("/PLAN.md")))
  '
  assert_call_result "$label runs the complete suite with raw success" \
    "./verify-all.sh" false "full suite failures: 0"
  jq_assert "$label complete-suite output covers all required check classes" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "./verify-all.sh")] | first) as $suite
    | any(.[];
      .kind == "result" and .id == $suite.id
      and (.content | contains("FOCUSED LABEL CHECK PASS"))
      and (.content | contains("STATIC CHECK PASS"))
      and (.content | contains("INTEGRATION CHECK PASS"))
      and (.content | contains("ALL VERIFICATION PASSED"))
    )
  '
  jq_assert "$label inspects the current diff after the suite" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "./verify-all.sh")] | first) as $suite
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "git diff")] | first) as $diff
    | $diff != null and $diff.order > $suite.order
      and any(.[]; .kind == "result" and .id == $diff.id and (.content | contains("+export const label = \"Ready!\";")))
  '
  jq_assert "$label individually verifies all three spec requirements" '
    [.[] | select(.kind == "call" and .name == "Bash") | .command] as $commands
    | any($commands[]; contains("label !== '\''Ready!'\''"))
      and any($commands[]; . == "node --check src/label.js")
      and any($commands[]; . == "./test/integration.sh")
  '
  if strict_labels_pass "$NORMALIZED"; then
    pass "$label marks every written requirement and plan item PASS"
  else
    fail "$label marks every written requirement and plan item PASS"
  fi
}

run_self_tests() {
  local masked special broad missing positive
  masked="$(mktemp)"; special="$(mktemp)"; broad="$(mktemp)"; missing="$(mktemp)"; positive="$(mktemp)"
  printf '%s\n' '[{"kind":"call","name":"Bash","command":"npm test; echo $?","id":"masked"}]' > "$masked"
  if commands_are_unmasked "$masked"; then
    fail "negative self-test rejects masked exit status"
  else
    pass "negative self-test rejects masked exit status"
  fi
  printf '%s\n' '[{"kind":"call","name":"Edit","old_string":"return value * 2;","new_string":"if (value === 4) return 12;"}]' > "$special"
  if jq -e '
    any(.[];
      .kind == "call" and .name == "Edit"
      and (.old_string | contains("return value * 2;"))
      and (.new_string | contains("return value * 3;"))
      and (.new_string | test("if[[:space:]]*\\(|===|==") | not)
    )
  ' "$special" >/dev/null; then
    fail "negative self-test rejects a special-case patch"
  else
    pass "negative self-test rejects a special-case patch"
  fi
  printf '%s\n' '[{"kind":"text","content":"The focused check passed, so all work is complete."}]' > "$broad"
  if jq -e '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | ($text | test("narrow claim"; "i"))
      and ($text | test("no broader claim|did not run.*verify-all"; "i"))
  ' "$broad" >/dev/null; then
    fail "negative self-test rejects broad claims from focused evidence"
  else
    pass "negative self-test rejects broad claims from focused evidence"
  fi
  printf '%s\n' '[{"kind":"text","content":"SPEC label exact — PASS\nSPEC syntax valid — PASS\nSPEC integrated import — PASS\nPLAN complete suite — PASS\nPLAN output and exit status — PASS\nPLAN current diff — PASS"}]' > "$missing"
  if strict_labels_pass "$missing"; then
    fail "negative self-test rejects a missing strict plan assertion"
  else
    pass "negative self-test rejects a missing strict plan assertion"
  fi
  printf '%s\n' '[{"kind":"call","name":"Bash","command":"npm test","id":"clean"},{"kind":"call","name":"Edit","old_string":"return value * 2;","new_string":"return value * 3;"},{"kind":"text","content":"SPEC label exact — PASS\nSPEC syntax valid — PASS\nSPEC integrated import — PASS\nPLAN complete suite — PASS\nPLAN output and exit status — PASS\nPLAN current diff — PASS\nPLAN requirements checked — PASS"}]' > "$positive"
  commands_are_unmasked "$positive" \
    && pass "positive self-test accepts a standalone command" \
    || fail "positive self-test accepts a standalone command"
  strict_labels_pass "$positive" \
    && pass "positive self-test accepts complete strict assertions" \
    || fail "positive self-test accepts complete strict assertions"
}

case "$CASE" in
  lean-debug) validate_lean_debug ;;
  standard-debug) validate_standard_debug ;;
  strict-debug) validate_strict_debug ;;
  lean-verify) validate_lean_verify ;;
  standard-verify) validate_standard_verify ;;
  strict-verify) validate_strict_verify ;;
  self-test) run_self_tests ;;
  all)
    validate_lean_debug
    validate_standard_debug
    validate_strict_debug
    validate_lean_verify
    validate_standard_verify
    validate_strict_verify
    run_self_tests
    ;;
  *)
    printf 'usage: %s [evidence-root] [lean-debug|standard-debug|strict-debug|lean-verify|standard-verify|strict-verify|self-test|all]\n' "$0" >&2
    exit 2
    ;;
esac

finish
