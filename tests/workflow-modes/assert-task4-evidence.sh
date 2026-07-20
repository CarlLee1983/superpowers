#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

EVIDENCE_ROOT="${1:-/tmp/superpowers-mode-evals/task-4}"
CASE="${2:-all}"
NORMALIZED=""
SUCCESS_FORBIDDEN='(^|[^[:alnum:]_])(FAIL|FAILED)([^[:alnum:]_]|$)|(?i:not[[:space:]]+ok)|(?i:(fail|failed|failure|failures|failing|error|errors)[[:space:]]*[:=]?[[:space:]]*0*[1-9][0-9]*|0*[1-9][0-9]*[[:space:]]+(fail|failed|failure|failures|failing|error|errors)|#[[:space:]]*fail[[:space:]]+0*[1-9][0-9]*)|Exit code[[:space:]]+0*[1-9][0-9]*'

normalize_transcript() {
  local transcript="$1" destination="$2"
  jq -s '
    def outer_error($e):
      if (($e.tool_use_result? // null) | type) == "string"
      then ($e.tool_use_result | startswith("Error:"))
      elif (($e.tool_use_result? // null) | type) == "object"
      then ($e.tool_use_result.is_error? // false)
      else false end;
    def outer_interrupted($e):
      if (($e.tool_use_result? // null) | type) == "object"
      then ($e.tool_use_result.interrupted? // false)
      else false end;
    def outer_exit($e):
      if (($e.tool_use_result? // null) | type) == "object"
      then ($e.tool_use_result.exit_code? // $e.tool_use_result.exitCode? // null)
      else null end;
    [
      to_entries[] as $entry
      | $entry.key as $outer
      | $entry.value as $event
      | if $event.type == "assistant"
        then $event.message.content | to_entries[]?
          | .key as $inner | .value
          | if .type == "tool_use"
            then {
              order:(($outer * 1000) + $inner), kind:"call",
              id:.id, name:.name,
              command:(.input.command? // ""),
              skill:(.input.skill? // ""),
              file_path:(.input.file_path? // ""),
              old_string:(.input.old_string? // ""),
              new_string:(.input.new_string? // ""),
              content:(.input.content? // "")
            }
            elif .type == "text"
            then {order:(($outer * 1000) + $inner),message_order:$outer,
                  kind:"text",content:.text}
            else empty end
        elif $event.type == "user"
        then $event.message.content | to_entries[]?
          | .key as $inner | .value
          | select(.type == "tool_result")
          | {
              order:(($outer * 1000) + $inner),kind:"result",
              id:.tool_use_id,content:(.content | tostring),
              is_error:(.is_error? // outer_error($event)),
              interrupted:outer_interrupted($event),
              exit_code:outer_exit($event)
            }
        else empty end
    ]
  ' "$transcript" > "$destination"
}

jq_assert() {
  local label="$1" filter="$2"
  if jq -e "$filter" "$NORMALIZED" >/dev/null; then pass "$label"; else fail "$label"; fi
}

load_case() {
  local label="$1" transcript="$2"
  if [[ ! -f "$transcript" ]]; then fail "$label transcript exists"; return 1; fi
  pass "$label transcript exists"
  NORMALIZED="$(mktemp)"
  normalize_transcript "$transcript" "$NORMALIZED"
}

bash_commands_match() {
  local file="$1" expected="$2"
  jq -e --argjson expected "$expected" '
    [.[] | select(.kind == "call" and .name == "Bash") | .command] == $expected
  ' "$file" >/dev/null
}

assert_exact_bash_commands() {
  local label="$1" expected="$2"
  if bash_commands_match "$NORMALIZED" "$expected"; then
    pass "$label uses the exact standalone Bash allowlist"
  else
    fail "$label uses the exact standalone Bash allowlist"
  fi
}

call_results_are_correlated() {
  local file="$1"
  jq -e '
    . as $events
    | all($events[] | select(.kind == "call");
        . as $call
        | ([$events[] | select(.kind == "result" and .id == $call.id)])
          as $results
        | ($results | length) == 1 and $results[0].order > $call.order)
      and all($events[] | select(.kind == "result");
        . as $result
        | ([$events[] | select(.kind == "call" and .id == $result.id)]
           | length) == 1)
  ' "$file" >/dev/null
}

assert_common() {
  local label="$1" expected_skills="$2"
  jq_assert "$label invokes exactly the expected process skill calls" "
    [.[] | select(.kind == \"call\" and .name == \"Skill\") | .skill]
    == $expected_skills
  "
  if call_results_are_correlated "$NORMALIZED"; then
    pass "$label has exactly one total later result per call and no orphan results"
  else
    fail "$label has exactly one total later result per call and no orphan results"
  fi
}

unique_bash_result_matches() {
  local file="$1" command="$2" expected_error="$3" required="$4"
  jq -e --arg command "$command" --argjson error "$expected_error" \
    --arg required "$required" --arg forbidden "$SUCCESS_FORBIDDEN" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == $command)])
      as $calls
    | ($calls | length) == 1
      and ([.[] | select(.kind == "result" and .id == $calls[0].id)]) as $results
      | ($results | length) == 1
        and $results[0].order > $calls[0].order
        and $results[0].is_error == $error
        and $results[0].interrupted == false
        and (if $error
             then ($results[0].exit_code == null or $results[0].exit_code != 0)
             else ($results[0].exit_code == null or $results[0].exit_code == 0)
               and ($results[0].content | test($forbidden; "m") | not)
             end)
        and ($required == "" or ($results[0].content | test($required; "m")))
  ' "$file" >/dev/null
}

assert_unique_bash_result() {
  local label="$1" command="$2" error="$3" required="$4"
  if unique_bash_result_matches "$NORMALIZED" "$command" "$error" "$required"; then
    pass "$label"
  else
    fail "$label"
  fi
}

mutations_match() {
  local file="$1" edit_path="$2" old="$3" new="$4"
  local write_path="${5:-}" write_content="${6:-}"
  jq -e --arg edit_path "$edit_path" --arg old "$old" --arg new "$new" \
    --arg write_path "$write_path" --arg write_content "$write_content" '
    . as $events
    | [.[] | select(.kind == "call" and (.name == "Edit" or .name == "Write"))]
      as $m
    | (if $write_path == ""
      then ($m | length) == 1
        and $m[0].name == "Edit" and $m[0].file_path == $edit_path
        and $m[0].old_string == $old and $m[0].new_string == $new
      else ($m | length) == 2
        and $m[0].name == "Write" and $m[0].file_path == $write_path
        and $m[0].content == $write_content
        and $m[1].name == "Edit" and $m[1].file_path == $edit_path
        and $m[1].old_string == $old and $m[1].new_string == $new
      end)
      and all($m[];
        . as $mutation
        | ([$events[] | select(.kind == "result" and .id == $mutation.id)])
          as $results
        | ($results | length) == 1 and $results[0].order > $mutation.order
          and $results[0].is_error == false and $results[0].interrupted == false
          and ($results[0].exit_code == null or $results[0].exit_code == 0))
  ' "$file" >/dev/null
}

assert_exact_mutations() {
  local label="$1" edit_path="$2" old="$3" new="$4"
  local write_path="${5:-}" write_content="${6:-}"
  if mutations_match "$NORMALIZED" "$edit_path" "$old" "$new" \
    "$write_path" "$write_content"; then
    pass "$label has only the exact expected general edit/write"
  else
    fail "$label has only the exact expected general edit/write"
  fi
}

assert_no_mutations() {
  jq_assert "$1 performs no Edit or Write calls" '
    [.[] | select(.kind == "call" and (.name == "Edit" or .name == "Write"))]
    | length == 0
  '
}

diff_result_matches() {
  local file="$1" command="$2" headers="$3" removed="$4" added="$5"
  jq -e --arg command "$command" --argjson headers "$headers" \
    --argjson removed "$removed" --argjson added "$added" \
    --arg forbidden "$SUCCESS_FORBIDDEN" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == $command)])
      as $calls
    | ($calls | length) == 1
      and ([.[] | select(.kind == "result" and .id == $calls[0].id)]) as $results
      | ($results | length) == 1
        and $results[0].order > $calls[0].order
        and $results[0].is_error == false and $results[0].interrupted == false
        and ($results[0].exit_code == null or $results[0].exit_code == 0)
        and ($results[0].content | test($forbidden; "m") | not)
        and ([$results[0].content | split("\n")[]
          | select(startswith("diff --git "))] == $headers)
        and ([$results[0].content | split("\n")[]
          | select(startswith("-") and (startswith("---") | not))] == $removed)
        and ([$results[0].content | split("\n")[]
          | select(startswith("+") and (startswith("+++") | not))] == $added)
  ' "$file" >/dev/null
}

assert_exact_diff() {
  local label="$1" command="$2" headers="$3" removed="$4" added="$5"
  if diff_result_matches "$NORMALIZED" "$command" "$headers" "$removed" "$added"; then
    pass "$label diff contains only the exact expected hunks"
  else
    fail "$label diff contains only the exact expected hunks"
  fi
}

assert_exact_read_result() {
  local label="$1" path="$2" required="$3"
  jq -e --arg path "$path" --arg required "$required" '
    ([.[] | select(.kind == "call" and .name == "Read" and .file_path == $path)])
      as $calls
    | ($calls | length) == 1
      and ([.[] | select(.kind == "result" and .id == $calls[0].id)])
        as $results
      | ($results | length) == 1 and $results[0].order > $calls[0].order
        and $results[0].is_error == false and $results[0].interrupted == false
        and ($results[0].exit_code == null or $results[0].exit_code == 0)
        and ($results[0].content | contains($required))
  ' "$NORMALIZED" >/dev/null \
    && pass "$label" || fail "$label"
}

status_result_matches() {
  local file="$1" command="$2" expected="$3"
  jq -e --arg command "$command" --argjson expected "$expected" \
    --arg forbidden "$SUCCESS_FORBIDDEN" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == $command)])
      as $calls
    | ($calls | length) == 1
      and ([.[] | select(.kind == "result" and .id == $calls[0].id)])
        as $results
      | ($results | length) == 1 and $results[0].order > $calls[0].order
        and $results[0].is_error == false and $results[0].interrupted == false
        and ($results[0].exit_code == null or $results[0].exit_code == 0)
        and ($results[0].content | test($forbidden; "m") | not)
        and ([$results[0].content | gsub("\\r"; "") | split("\n")[]
          | select(length > 0)] | sort) == ($expected | sort)
  ' "$file" >/dev/null
}

assert_exact_status() {
  local label="$1" command="$2" expected="$3"
  if status_result_matches "$NORMALIZED" "$command" "$expected"; then
    pass "$label has exactly the expected normalized status lines"
  else
    fail "$label has exactly the expected normalized status lines"
  fi
}

final_labels_pass() {
  local file="$1" expected="$2" bases="$3"
  jq -e --argjson expected "$expected" --argjson bases "$bases" '
    def occurrences($text; $needle):
      (($text | split($needle) | length) - 1);
    . as $events
    | ([.[] | select(.kind == "result") | .order] | max // -1) as $last_result
    | ([.[] | select(.kind == "text") | (.message_order // .order)] | max)
      as $final_message
    | ([.[] | select(.kind == "text"
          and (.message_order // .order) == $final_message) | .content]
       | join("\n")) as $final
    | ([.[] | select(.kind == "text" and .order > $last_result) | .content]
       | join("\n")) as $after
    | ([.[] | select(.kind == "text"
          and (.message_order // .order) == $final_message) | .order] | min)
      as $final_order
    | $final_order > $last_result
      and all($expected[];
        . as $label
        | occurrences($final; $label) == 1
          and occurrences($after; $label) == 1)
      and all($bases[];
        . as $base
        | occurrences($final; $base) == 1
          and occurrences($after; $base) == 1)
      and ($after | test("(^|[^[:alnum:]_])(FAIL|FAILED)([^[:alnum:]_]|$)|(?i:not[[:space:]]+ok)"; "m") | not)
  ' "$file" >/dev/null
}

strict_labels_pass() {
  local file="$1"
  final_labels_pass "$file" \
    '["SPEC label exact — PASS","SPEC syntax valid — PASS","SPEC integrated import — PASS","PLAN complete suite — PASS","PLAN output and exit status — PASS","PLAN current diff — PASS","PLAN requirements checked — PASS"]' \
    '["SPEC label exact","SPEC syntax valid","SPEC integrated import","PLAN complete suite","PLAN output and exit status","PLAN current diff","PLAN requirements checked"]'
}

strict_debug_labels_pass() {
  local file="$1"
  final_labels_pass "$file" \
    '["PHASES: 1,2,3,4","DEPTH: STRICT_FULL_TDD"]' \
    '["PHASES:","DEPTH:"]'
}

validate_lean_debug() {
  local label="lean debugging" check expected
  check='node --input-type=module -e "import { double } from '\''./src/double.js'\''; if (double(3) !== 6) { console.error('\''expected 6, got'\'', double(3)); process.exit(1) }"'
  expected="$(jq -cn --arg check "$check" \
    '[$check,"git log --oneline -5","git show HEAD -- src/double.js",
      $check,"git status --short","git diff -- src/double.js"]')"
  load_case "$label" "$EVIDENCE_ROOT/systematic-debugging/green/transcript.jsonl" || return
  assert_common "$label" '["superpowers:systematic-debugging"]'
  assert_exact_bash_commands "$label" "$expected"
  jq_assert "$label has exactly the expected reproduction failure" \
    '[.[] | select(.kind == "result" and .is_error == true)] | length == 1'
  jq_assert "$label has one failing then one successful exact reproduction" '
    [.[] | select(.kind == "call" and .name == "Bash"
      and (.command | contains("import { double }")))] as $checks
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | ($checks | length) == 2 and $checks[0].order < $edit.order
      and $checks[1].order > $edit.order
      and ([.[] | select(.kind == "result" and .id == $checks[0].id
        and .is_error == true and .interrupted == false
        and (.content | test("Exit code 1(.|\n)*expected 6, got 7")))] | length) == 1
      and ([.[] | select(.kind == "result" and .id == $checks[1].id
        and .is_error == false and .interrupted == false
        and (.exit_code == null or .exit_code == 0)
        and (.content | test("Exit code [1-9]") | not))] | length) == 1
  '
  assert_unique_bash_result "$label gets one clean root-cause history result" \
    "git show HEAD -- src/double.js" false \
    'regression: add offset to double result(.|\n)*\+  return value \* 2 \+ 1;'
  assert_exact_mutations "$label" \
    "/private/tmp/superpowers-mode-evals/task-4/systematic-debugging/green/workspace/src/double.js" \
    "  return value * 2 + 1;" "  return value * 2;"
  jq_assert "$label edits after its root-cause result" '
    ([.[] | select(.kind == "call" and .name == "Bash"
      and .command == "git show HEAD -- src/double.js")][0]) as $call
    | ([.[] | select(.kind == "result" and .id == $call.id)][0]) as $result
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | $result.order < $edit.order
  '
  assert_unique_bash_result "$label inspects post-edit status" \
    "git status --short" false 'src/double.js'
  assert_exact_diff "$label" "git diff -- src/double.js" \
    '["diff --git a/src/double.js b/src/double.js"]' \
    '["-  return value * 2 + 1;"]' '["+  return value * 2;"]'
}

validate_standard_debug() {
  local label="standard debugging" check hypothesis expected
  check='node --input-type=module -e "import { triple } from '\''./src/triple.js'\''; if (triple(4) !== 12) { console.error('\''expected 12, got'\'', triple(4)); process.exit(1) }"'
  hypothesis="git diff HEAD^ HEAD -- src/triple.js"
  expected="$(jq -cn --arg check "$check" --arg hypothesis "$hypothesis" \
    '[$check,"git log --oneline -2",$hypothesis,$check,
      "git status --short","git diff -- src/triple.js"]')"
  load_case "$label" \
    "$EVIDENCE_ROOT/systematic-debugging/green/standard-positive/transcript.jsonl" || return
  assert_common "$label" '["superpowers:systematic-debugging"]'
  assert_exact_bash_commands "$label" "$expected"
  jq_assert "$label has exactly the expected reproduction failure" \
    '[.[] | select(.kind == "result" and .is_error == true)] | length == 1'
  jq -e --arg hypothesis "$hypothesis" '
    ([.[] | select(.kind == "text" and (.content | test("(?m)^HYPOTHESIS: ")))])
      as $texts
    | ([.[] | select(.kind == "call" and .name == "Bash"
      and .command == $hypothesis)]) as $tests
    | ([.[] | select(.kind == "call" and .name == "Edit")]) as $edits
    | ($texts | length) == 1 and ($tests | length) == 1 and ($edits | length) == 1
      and $texts[0].order < $tests[0].order and $tests[0].order < $edits[0].order
  ' "$NORMALIZED" >/dev/null \
    && pass "$label states one HYPOTHESIS before its distinct test and edit" \
    || fail "$label states one HYPOTHESIS before its distinct test and edit"
  assert_unique_bash_result "$label has one successful evidence-bearing hypothesis result" \
    "$hypothesis" false \
    'diff --git a/src/triple.js b/src/triple.js(.|\n)*-  return value \* 3;(.|\n)*\+  return value \* 2;'
  jq -e --arg hypothesis "$hypothesis" '
    ([.[] | select(.kind == "call" and .name == "Bash"
      and .command == $hypothesis)][0]) as $call
    | ([.[] | select(.kind == "result" and .id == $call.id)][0]) as $result
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | $call.order < $result.order and $result.order < $edit.order
  ' "$NORMALIZED" >/dev/null \
    && pass "$label receives hypothesis-test evidence before editing" \
    || fail "$label receives hypothesis-test evidence before editing"
  jq -e --arg hypothesis "$hypothesis" '
    ([.[] | select(.kind == "call" and .name == "Bash"
      and .command == $hypothesis)][0]) as $call
    | ([.[] | select(.kind == "result" and .id == $call.id)][0]) as $result
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | any(.[]; .kind == "text" and .order > $result.order and .order < $edit.order
      and (.content | test("Hypothesis confirmed|general fix|root cause"; "i")))
  ' "$NORMALIZED" >/dev/null \
    && pass "$label justifies the general fix from the hypothesis result" \
    || fail "$label justifies the general fix from the hypothesis result"
  assert_exact_mutations "$label" \
    "/private/tmp/superpowers-mode-evals/task-4/systematic-debugging/green/standard-positive/workspace/src/triple.js" \
    "  return value * 2;" "  return value * 3;"
  jq_assert "$label has one failing then one successful exact reproduction" '
    [.[] | select(.kind == "call" and .name == "Bash"
      and (.command | contains("import { triple }")))] as $checks
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | ($checks | length) == 2 and $checks[0].order < $edit.order
      and $checks[1].order > $edit.order
      and ([.[] | select(.kind == "result" and .id == $checks[0].id
        and .is_error == true and .interrupted == false
        and (.content | test("Exit code 1(.|\n)*expected 12, got 8")))] | length) == 1
      and ([.[] | select(.kind == "result" and .id == $checks[1].id
        and .is_error == false and .interrupted == false
        and (.exit_code == null or .exit_code == 0)
        and (.content | test("Exit code [1-9]") | not))] | length) == 1
  '
  assert_unique_bash_result "$label inspects post-edit status" \
    "git status --short" false 'src/triple.js'
  assert_exact_diff "$label" "git diff -- src/triple.js" \
    '["diff --git a/src/triple.js b/src/triple.js"]' \
    '["-  return value * 2;"]' '["+  return value * 3;"]'
}

validate_strict_debug() {
  local label="strict debugging" check hypothesis diff_command expected test_content
  check='node --input-type=module -e "import { quadruple } from '\''./src/quadruple.js'\''; if (quadruple(3) !== 12) { console.error('\''expected 12, got'\'', quadruple(3)); process.exit(1) }"'
  hypothesis='node --input-type=module -e "const quadruple = (value) => value * 4; if (quadruple(3) !== 12) { process.exit(1) }; console.log('\''hypothesis confirmed: value * 4 yields 12'\'')"'
  diff_command="git diff"
  test_content="$(printf '%s\n' \
    "import assert from 'node:assert/strict';" \
    "import { quadruple } from '../src/quadruple.js';" \
    "" \
    "assert.equal(quadruple(3), 12, 'quadruple(3) should be 12');" \
    "assert.equal(quadruple(5), 20, 'quadruple(5) should be 20');" \
    "assert.equal(quadruple(-2), -8, 'quadruple(-2) should be -8');" \
    "" \
    "console.log('quadruple regression tests passed');")"
  test_content+=$'\n'
  expected="$(jq -cn --arg check "$check" --arg hypothesis "$hypothesis" \
    --arg diff "$diff_command" \
    '[$check,"git show HEAD -- src/quadruple.js",$hypothesis,
      "npm test","npm test",$check,"git add -N test/quadruple.test.js",
      "git status --short",$diff]')"
  load_case "$label" \
    "$EVIDENCE_ROOT/systematic-debugging/green/strict-positive/transcript.jsonl" || return
  assert_common "$label" \
    '["superpowers:systematic-debugging","superpowers:test-driven-development"]'
  assert_exact_bash_commands "$label" "$expected"
  jq_assert "$label has only the reproduction and RED failures" \
    '[.[] | select(.kind == "result" and .is_error == true)] | length == 2'
  assert_unique_bash_result "$label has one clean Phase-1 root-cause result" \
    "git show HEAD -- src/quadruple.js" false \
    'regression: use triple multiplier in quadruple(.|\n)*-  return value \* 4;(.|\n)*\+  return value \* 3;'
  assert_unique_bash_result "$label has one clean hypothesis-test result" \
    "$hypothesis" false 'hypothesis confirmed: value \* 4 yields 12'
  assert_exact_mutations "$label" \
    "/private/tmp/superpowers-mode-evals/task-4/systematic-debugging/green/strict-positive/workspace/src/quadruple.js" \
    "  return value * 3;" "  return value * 4;" \
    "/private/tmp/superpowers-mode-evals/task-4/systematic-debugging/green/strict-positive/workspace/test/quadruple.test.js" \
    "$test_content"
  jq_assert "$label observes exact permanent-test RED before source edit" '
    ([.[] | select(.kind == "call" and .name == "Write")][0]) as $write
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test")])
      as $tests
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | ($tests | length) == 2 and $write.order < $tests[0].order
      and $tests[0].order < $edit.order
      and ([.[] | select(.kind == "result" and .id == $tests[0].id
        and .is_error == true and .interrupted == false
        and (.content | test("Exit code 1(.|\n)*9 !== 12")))] | length) == 1
  '
  jq -e --arg forbidden "$SUCCESS_FORBIDDEN" '
    ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test")])
      as $tests
    | $edit.order < $tests[1].order
      and ([.[] | select(.kind == "result" and .id == $tests[1].id
        and .is_error == false and .interrupted == false
        and (.exit_code == null or .exit_code == 0)
        and (.content | contains("quadruple regression tests passed"))
        and (.content | test($forbidden; "m") | not))]
        | length) == 1
  ' "$NORMALIZED" >/dev/null \
    && pass "$label observes exact GREEN after source edit" \
    || fail "$label observes exact GREEN after source edit"
  jq_assert "$label reruns the original regression successfully after GREEN" '
    ([.[] | select(.kind == "call" and .name == "Bash" and .command == "npm test")][1])
      as $green
    | ([.[] | select(.kind == "call" and .name == "Bash"
      and (.command | contains("import { quadruple }")))]) as $checks
    | ($checks | length) == 2 and $checks[1].order > $green.order
      and ([.[] | select(.kind == "result" and .id == $checks[1].id
        and .is_error == false and .interrupted == false
        and (.exit_code == null or .exit_code == 0)
        and (.content | test("Exit code [1-9]") | not))] | length) == 1
  '
  assert_unique_bash_result "$label records intent-to-add successfully" \
    "git add -N test/quadruple.test.js" false ''
  assert_exact_status "$label" "git status --short" \
    '[" M src/quadruple.js"," A test/quadruple.test.js"]'
  jq -e --arg diff "$diff_command" '
    ([.[] | select(.kind == "call" and .name == "Write")][0]) as $write
    | ([.[] | select(.kind == "call" and .name == "Edit")][0]) as $edit
    | ([.[] | select(.kind == "call" and .name == "Bash"
      and .command == "git status --short")][0]) as $status
    | ([.[] | select(.kind == "call" and .name == "Bash"
      and .command == "git add -N test/quadruple.test.js")][0]) as $intent
    | ([.[] | select(.kind == "call" and .name == "Bash" and .command == $diff)][0])
      as $diff_call
    | $intent.order > $write.order and $intent.order > $edit.order
      and $status.order > $intent.order and $diff_call.order > $status.order
  ' "$NORMALIZED" >/dev/null \
    && pass "$label orders intent-to-add, exact status, and unscoped diff" \
    || fail "$label orders intent-to-add, exact status, and unscoped diff"
  assert_exact_diff "$label" "$diff_command" \
    '["diff --git a/src/quadruple.js b/src/quadruple.js","diff --git a/test/quadruple.test.js b/test/quadruple.test.js"]' \
    '["-  return value * 3;"]' \
    '["+  return value * 4;","+import assert from '\''node:assert/strict'\'';","+import { quadruple } from '\''../src/quadruple.js'\'';","+","+assert.equal(quadruple(3), 12, '\''quadruple(3) should be 12'\'');","+assert.equal(quadruple(5), 20, '\''quadruple(5) should be 20'\'');","+assert.equal(quadruple(-2), -8, '\''quadruple(-2) should be -8'\'');","+","+console.log('\''quadruple regression tests passed'\'');"]'
  if strict_debug_labels_pass "$NORMALIZED"; then
    pass "$label reports exact phase/depth labels once in the final response"
  else
    fail "$label reports exact phase/depth labels once in the final response"
  fi
}

validate_lean_verify() {
  local label="lean verification"
  load_case "$label" \
    "$EVIDENCE_ROOT/verification-before-completion/green/transcript.jsonl" || return
  assert_common "$label" '["superpowers:verification-before-completion"]'
  assert_exact_bash_commands "$label" '["./test/label.test.sh","git diff"]'
  assert_no_mutations "$label"
  assert_unique_bash_result "$label gets one clean focused result with zero failures" \
    "./test/label.test.sh" false \
    'FOCUSED LABEL CHECK PASS(.|\n)*focused failures: 0'
  assert_exact_diff "$label" "git diff" \
    '["diff --git a/src/label.js b/src/label.js"]' \
    '["-export const label = \"Ready\";"]' \
    '["+export const label = \"Ready!\";"]'
  jq_assert "$label scopes the final claim narrowly" '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | ($text | test("narrow claim"; "i"))
      and ($text | test("no broader claim|did not run.*verify-all"; "i"))
  '
}

validate_standard_verify() {
  local label="standard verification"
  load_case "$label" \
    "$EVIDENCE_ROOT/verification-before-completion/green/standard-positive/transcript.jsonl" || return
  assert_common "$label" '["superpowers:verification-before-completion"]'
  assert_exact_bash_commands "$label" \
    '["git diff","./test/label.test.sh","./test/static.sh","./test/integration.sh"]'
  assert_no_mutations "$label"
  assert_unique_bash_result "$label gets one clean relevant-test result" \
    "./test/label.test.sh" false \
    'FOCUSED LABEL CHECK PASS(.|\n)*focused failures: 0'
  assert_unique_bash_result "$label gets one clean static result" \
    "./test/static.sh" false 'STATIC CHECK PASS(.|\n)*static failures: 0'
  assert_unique_bash_result "$label gets one clean integrated result" \
    "./test/integration.sh" false \
    'INTEGRATION CHECK PASS(.|\n)*integration failures: 0'
  assert_exact_diff "$label" "git diff" \
    '["diff --git a/src/label.js b/src/label.js","diff --git a/verify-all.sh b/verify-all.sh"]' \
    '["-export const label = \"Ready\";","-node --check src/label.js","-printf '\''STATIC CHECK PASS\\n'\''","-node --input-type=module -e \"import { label } from '\''./src/label.js'\''; console.log('\''INTEGRATION CHECK PASS:'\'', label)\""]' \
    '["+export const label = \"Ready!\";","+./test/static.sh","+./test/integration.sh"]'
  jq_assert "$label does not claim strict complete-suite coverage" '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | ($text | test("未執行.*verify-all|did not run.*verify-all"; "i"))
  '
}

validate_strict_verify() {
  local label="strict verification" exact expected
  exact='node --input-type=module -e "import { label } from '\''./src/label.js'\''; if (label !== '\''Ready!'\'') { console.error('\''MISMATCH:'\'', JSON.stringify(label)); process.exit(1); } console.log('\''exact match:'\'', JSON.stringify(label));"'
  expected="$(jq -cn --arg exact "$exact" \
    '["./verify-all.sh","git diff",$exact,"node --check src/label.js",
      "./test/integration.sh"]')"
  load_case "$label" \
    "$EVIDENCE_ROOT/verification-before-completion/green/strict-positive/transcript.jsonl" || return
  assert_common "$label" '["superpowers:verification-before-completion"]'
  assert_exact_bash_commands "$label" "$expected"
  assert_no_mutations "$label"
  assert_exact_read_result "$label reads one SPEC with one correlated result" \
    "/private/tmp/superpowers-mode-evals/task-4/verification-before-completion/green/strict-positive/workspace/SPEC.md" \
    "integrated ESM import observes exactly"
  assert_exact_read_result "$label reads one PLAN with one correlated result" \
    "/private/tmp/superpowers-mode-evals/task-4/verification-before-completion/green/strict-positive/workspace/PLAN.md" \
    "Check every requirement"
  assert_unique_bash_result "$label has one clean full-suite result with zero failures" \
    "./verify-all.sh" false \
    'FULL SUITE START(.|\n)*FOCUSED LABEL CHECK PASS(.|\n)*focused failures: 0(.|\n)*STATIC CHECK PASS(.|\n)*static failures: 0(.|\n)*INTEGRATION CHECK PASS(.|\n)*integration failures: 0(.|\n)*ALL VERIFICATION PASSED(.|\n)*full suite failures: 0'
  assert_unique_bash_result "$label has one clean exact-label result" \
    "$exact" false 'exact match: "Ready!"'
  assert_unique_bash_result "$label has one clean individual syntax result" \
    "node --check src/label.js" false ''
  assert_unique_bash_result "$label has one clean individual integration result" \
    "./test/integration.sh" false \
    'INTEGRATION CHECK PASS(.|\n)*integration failures: 0'
  assert_exact_diff "$label" "git diff" \
    '["diff --git a/src/label.js b/src/label.js","diff --git a/verify-all.sh b/verify-all.sh"]' \
    '["-export const label = \"Ready\";","-node --check src/label.js","-printf '\''STATIC CHECK PASS\\n'\''","-node --input-type=module -e \"import { label } from '\''./src/label.js'\''; console.log('\''INTEGRATION CHECK PASS:'\'', label)\""]' \
    '["+export const label = \"Ready!\";","+./test/static.sh","+./test/integration.sh"]'
  if strict_labels_pass "$NORMALIZED"; then
    pass "$label marks every requirement and plan item PASS exactly once"
  else
    fail "$label marks every requirement and plan item PASS exactly once"
  fi
}

expect_command_rejected() {
  local label="$1" command="$2" file="$3"
  jq -n --arg command "$command" \
    '[{kind:"call",name:"Bash",command:$command,id:"bad"}]' > "$file"
  if bash_commands_match "$file" '["npm test"]'; then
    fail "negative self-test rejects $label"
  else
    pass "negative self-test rejects $label"
  fi
}

expect_success_output_rejected() {
  local label="$1" content="$2" file="$3"
  jq -n --arg content "$content" '[
    {order:1,kind:"call",name:"Bash",command:"npm test",id:"test"},
    {order:2,kind:"result",id:"test",is_error:false,interrupted:false,
     exit_code:0,content:$content}
  ]' > "$file"
  if unique_bash_result_matches "$file" "npm test" false 'failures: 0'; then
    fail "negative self-test rejects $label"
  else
    pass "negative self-test rejects $label"
  fi
}

expect_success_output_accepted() {
  local label="$1" content="$2" file="$3"
  jq -n --arg content "$content" '[
    {order:1,kind:"call",name:"Bash",command:"npm test",id:"test"},
    {order:2,kind:"result",id:"test",is_error:false,interrupted:false,
     exit_code:0,content:$content}
  ]' > "$file"
  if unique_bash_result_matches "$file" "npm test" false 'PASS'; then
    pass "positive self-test accepts $label"
  else
    fail "positive self-test accepts $label"
  fi
}

run_self_tests() {
  local file decoy mixed duplicate_result duplicate_call mixed_success
  local pre_post_result missing_result status_extra strict_extra_diff broad early_labels
  local contradictory_labels command
  file="$(mktemp)"; decoy="$(mktemp)"; mixed="$(mktemp)"
  duplicate_result="$(mktemp)"; duplicate_call="$(mktemp)"
  mixed_success="$(mktemp)"; pre_post_result="$(mktemp)"
  missing_result="$(mktemp)"; status_extra="$(mktemp)"
  strict_extra_diff="$(mktemp)"; broad="$(mktemp)"
  early_labels="$(mktemp)"; contradictory_labels="$(mktemp)"

  expect_command_rejected "masked exit status" "npm test; echo $?" "$file"
  expect_command_rejected "pipe without spaces" "npm test|cat" "$file"
  expect_command_rejected "pipe without right space" "npm test |cat" "$file"
  expect_command_rejected "semicolon trailing command" "npm test; pwd" "$file"
  command=$'npm test\nprintf '\''masked\\n'\'''
  expect_command_rejected "newline trailing command" "$command" "$file"
  expect_command_rejected "and-list trailing command" \
    "npm test && printf pass" "$file"
  expect_command_rejected "or-list fallback" \
    "npm test || printf fallback" "$file"
  expect_command_rejected "command substitution" 'npm test $(pwd)' "$file"
  expect_command_rejected "backtick substitution" 'npm test `pwd`' "$file"
  expect_command_rejected "output redirect" "npm test > result.txt" "$file"

  jq -n '[
    {kind:"call",name:"Edit",file_path:"/fixture/src/triple.js",
     old_string:"  return value * 2;",new_string:"  return value * 3;"},
    {kind:"call",name:"Edit",file_path:"/fixture/src/triple.js",
     old_string:"  return value;",new_string:"  if (value === 4) return 12;"}
  ]' > "$decoy"
  if mutations_match "$decoy" "/fixture/src/triple.js" \
    "  return value * 2;" "  return value * 3;"; then
    fail "negative self-test rejects general fix plus special-case decoy edit"
  else
    pass "negative self-test rejects general fix plus special-case decoy edit"
  fi

  jq -n '[
    {order:1,kind:"call",name:"Bash",command:"git diff -- src/triple.js",id:"diff"},
    {order:2,kind:"result",id:"diff",is_error:false,interrupted:false,exit_code:0,
     content:"diff --git a/src/triple.js b/src/triple.js\n-  return value * 2;\n+  return value * 3;\ndiff --git a/src/other.js b/src/other.js\n+if (value === 4) return 12;"}
  ]' > "$mixed"
  if diff_result_matches "$mixed" "git diff -- src/triple.js" \
    '["diff --git a/src/triple.js b/src/triple.js"]' \
    '["-  return value * 2;"]' '["+  return value * 3;"]'; then
    fail "negative self-test rejects expected hunk plus harmful mixed diff"
  else
    pass "negative self-test rejects expected hunk plus harmful mixed diff"
  fi

  jq -n '[
    {order:1,kind:"call",name:"Bash",command:"npm test",id:"test"},
    {order:2,kind:"result",id:"test",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nfailures: 0"},
    {order:3,kind:"result",id:"test",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nfailures: 0"}
  ]' > "$duplicate_result"
  if unique_bash_result_matches "$duplicate_result" "npm test" false 'failures: 0'; then
    fail "negative self-test rejects duplicate correlated results"
  else
    pass "negative self-test rejects duplicate correlated results"
  fi

  jq -n '[
    {order:1,kind:"result",id:"test",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nfailures: 0"},
    {order:2,kind:"call",name:"Bash",command:"npm test",id:"test"},
    {order:3,kind:"result",id:"test",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nfailures: 0"}
  ]' > "$pre_post_result"
  if unique_bash_result_matches "$pre_post_result" "npm test" false 'failures: 0'; then
    fail "negative self-test rejects one pre-call plus one post-call result"
  else
    pass "negative self-test rejects one pre-call plus one post-call result"
  fi

  jq -n '[
    {order:1,kind:"call",name:"Bash",command:"npm test",id:"first"},
    {order:2,kind:"result",id:"first",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nfailures: 0"},
    {order:3,kind:"call",name:"Bash",command:"npm test",id:"second"},
    {order:4,kind:"result",id:"second",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nfailures: 0"}
  ]' > "$duplicate_call"
  if unique_bash_result_matches "$duplicate_call" "npm test" false 'failures: 0'; then
    fail "negative self-test rejects duplicate matching calls"
  else
    pass "negative self-test rejects duplicate matching calls"
  fi

  jq -n '[
    {order:1,kind:"call",name:"Bash",command:"npm test",id:"test"},
    {order:2,kind:"result",id:"test",is_error:false,interrupted:false,exit_code:0,
     content:"PASS\nFAIL\nfailures: 0"}
  ]' > "$mixed_success"
  if unique_bash_result_matches "$mixed_success" "npm test" false 'failures: 0'; then
    fail "negative self-test rejects mixed PASS and FAIL output"
  else
    pass "negative self-test rejects mixed PASS and FAIL output"
  fi

  jq -n '[{order:1,kind:"call",name:"Bash",command:"npm test",id:"test"}]' \
    > "$missing_result"
  if unique_bash_result_matches "$missing_result" "npm test" false 'failures: 0'; then
    fail "negative self-test rejects missing correlated result"
  else
    pass "negative self-test rejects missing correlated result"
  fi

  expect_success_output_rejected "FAILED output" \
    $'PASS\nFAILED\nfailures: 0' "$file"
  expect_success_output_rejected "not ok output" \
    $'PASS\nnot ok 1\nfailures: 0' "$file"
  expect_success_output_rejected "nonzero TAP fail count" \
    $'PASS\n# fail 1\nfailures: 0' "$file"
  expect_success_output_rejected "nonzero failure count" \
    $'PASS\nfailures: 2' "$file"
  expect_success_output_rejected "count-before-key failing form" \
    $'PASS\n1 failing\nfailures: 0' "$file"
  expect_success_output_rejected "count-before-key singular failure form" \
    $'PASS\n1 failure\nfailures: 0' "$file"
  expect_success_output_rejected "key-before-count plural error form" \
    $'PASS\nerrors: 1\nfailures: 0' "$file"
  expect_success_output_rejected "key-before-count singular error with leading zero" \
    $'PASS\nerror=01\nfailures: 0' "$file"
  expect_success_output_rejected "plural failures with leading zero" \
    $'PASS\nfailures: 01' "$file"
  expect_success_output_rejected "count-before-key plural errors with leading zero" \
    $'PASS\n01 errors\nfailures: 0' "$file"
  expect_success_output_rejected "count-before-key plural failures with leading zero" \
    $'PASS\n001 failures\nfailures: 0' "$file"
  expect_success_output_rejected "count-before-key failed form with leading zero" \
    $'PASS\n01 failed\nfailures: 0' "$file"
  expect_success_output_rejected "key-before-count singular failure with leading zero" \
    $'PASS\nfailure: 01\nfailures: 0' "$file"
  expect_success_output_rejected "key-before-count failing form with leading zero" \
    $'PASS\nfailing=001\nfailures: 0' "$file"
  expect_success_output_accepted "explicit zero counters" \
    $'PASS\n# fail 0\n0 failed\n0 failing\n0 failure\n0 failures\n0 errors\nerror=00\nfailure: 000\nfailures: 000' "$file"

  jq -n '[
    {order:1,kind:"call",name:"Bash",command:"git status --short",id:"status"},
    {order:2,kind:"result",id:"status",is_error:false,interrupted:false,
     exit_code:0,content:" M src/quadruple.js\n A test/quadruple.test.js\n?? notes.txt"}
  ]' > "$status_extra"
  if status_result_matches "$status_extra" "git status --short" \
    '[" M src/quadruple.js"," A test/quadruple.test.js"]'; then
    fail "negative self-test rejects extra strict status lines"
  else
    pass "negative self-test rejects extra strict status lines"
  fi

  jq -n '[
    {order:1,kind:"call",name:"Bash",command:"git diff",id:"diff"},
    {order:2,kind:"result",id:"diff",is_error:false,interrupted:false,exit_code:0,
     content:"diff --git a/src/quadruple.js b/src/quadruple.js\n-  return value * 3;\n+  return value * 4;\ndiff --git a/test/quadruple.test.js b/test/quadruple.test.js\n+permanent test\ndiff --git a/notes.txt b/notes.txt\n+unexpected"}
  ]' > "$strict_extra_diff"
  if diff_result_matches "$strict_extra_diff" "git diff" \
    '["diff --git a/src/quadruple.js b/src/quadruple.js","diff --git a/test/quadruple.test.js b/test/quadruple.test.js"]' \
    '["-  return value * 3;"]' \
    '["+  return value * 4;","+permanent test"]'; then
    fail "negative self-test rejects extra files in strict unscoped diff"
  else
    pass "negative self-test rejects extra files in strict unscoped diff"
  fi

  jq -n '[{kind:"text",content:"The focused check passed, so all work is complete."}]' \
    > "$broad"
  if jq -e '
    ([.[] | select(.kind == "text") | .content] | join("\n")) as $text
    | ($text | test("narrow claim"; "i"))
      and ($text | test("no broader claim|did not run.*verify-all"; "i"))
  ' "$broad" >/dev/null; then
    fail "negative self-test rejects broad claims from focused evidence"
  else
    pass "negative self-test rejects broad claims from focused evidence"
  fi

  jq -n '[{order:1,message_order:1,kind:"text",content:"SPEC label exact — PASS\nSPEC syntax valid — PASS\nSPEC integrated import — PASS\nPLAN complete suite — PASS\nPLAN output and exit status — PASS\nPLAN current diff — PASS"}]' \
    > "$file"
  if strict_labels_pass "$file"; then
    fail "negative self-test rejects missing strict plan assertion"
  else
    pass "negative self-test rejects missing strict plan assertion"
  fi

  jq -n '[
    {order:1,kind:"text",content:"SPEC label exact — PASS\nSPEC syntax valid — PASS\nSPEC integrated import — PASS\nPLAN complete suite — PASS\nPLAN output and exit status — PASS\nPLAN current diff — PASS\nPLAN requirements checked — PASS"},
    {order:2,kind:"call",name:"Bash",command:"npm test",id:"test"},
    {order:3,kind:"result",id:"test",is_error:false,interrupted:false,
     exit_code:0,content:"PASS"},
    {order:4,kind:"text",content:"Final response without requirement labels."}
  ]' > "$early_labels"
  if strict_labels_pass "$early_labels"; then
    fail "negative self-test rejects labels that appear only before final evidence"
  else
    pass "negative self-test rejects labels that appear only before final evidence"
  fi

  jq -n '[
    {order:1,kind:"result",id:"test",is_error:false,interrupted:false,
     exit_code:0,content:"PASS"},
    {order:2,kind:"text",content:"SPEC label exact — PASS\nSPEC label exact — FAIL\nSPEC syntax valid — PASS\nSPEC integrated import — PASS\nPLAN complete suite — PASS\nPLAN output and exit status — PASS\nPLAN current diff — PASS\nPLAN requirements checked — PASS"}
  ]' > "$contradictory_labels"
  if strict_labels_pass "$contradictory_labels"; then
    fail "negative self-test rejects PASS followed by contradictory FAIL"
  else
    pass "negative self-test rejects PASS followed by contradictory FAIL"
  fi

  jq -n '[
    {order:1,message_order:1,kind:"call",name:"Bash",command:"npm test",id:"clean"},
    {order:2,message_order:2,kind:"result",id:"clean",is_error:false,
     interrupted:false,exit_code:0,content:"PASS"},
    {order:3,message_order:3,kind:"text",content:"SPEC label exact — PASS\nSPEC syntax valid — PASS\nSPEC integrated import — PASS\nPLAN complete suite — PASS\nPLAN output and exit status — PASS\nPLAN current diff — PASS\nPLAN requirements checked — PASS"}
  ]' > "$file"
  bash_commands_match "$file" '["npm test"]' \
    && pass "positive self-test accepts exact standalone command" \
    || fail "positive self-test accepts exact standalone command"
  strict_labels_pass "$file" \
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
    printf 'usage: %s [evidence-root] [lean-debug|standard-debug|strict-debug|lean-verify|standard-verify|strict-verify|self-test|all]\n' \
      "$0" >&2
    exit 2
    ;;
esac

finish
