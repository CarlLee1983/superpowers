#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/tests/workflow-modes/lib.sh"

EVIDENCE_ROOT="${1:-/tmp/superpowers-mode-evals/task-3/review-fix}"

jq_assert() {
  local transcript="$1" filter="$2" label="$3"
  if [[ -f "$transcript" ]] && jq -s -e "$filter" "$transcript" >/dev/null; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_clean_transcript() {
  local transcript="$1" label="$2"
  if [[ -f "$transcript" ]] &&
    ! rg -q 'MODULE_TYPELESS_PACKAGE_JSON' "$transcript"; then
    pass "$label"
  else
    fail "$label"
  fi
}

assert_safe_handoff() {
  local transcript="$1" label="$2"
  jq_assert "$transcript" '
    ([.[] | select(.type == "assistant") | .message.content[]? |
      select(.type == "tool_use" and .name == "Bash") |
      .input.command |
      select(test("(^|[;&|[:space:]])git[[:space:]]+(merge([[:space:]]|$)|push([[:space:]]|$)|branch[[:space:]]+(-d|-D)([[:space:]]|$)|worktree[[:space:]]+remove([[:space:]]|$))|gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)"; "i"))] |
      length) == 0 and
    ([.[] | select(.type == "result") | .result // "" |
      select(test("merged .+ locally|pushed .+|pull request (was )?created|keeping branch|discarded|deleted branch"; "i"))] |
      length) == 0
  ' "$label"
}

assert_direct_passing_npm_test() {
  local transcript="$1" label="$2"
  jq_assert "$transcript" '
    ([.[] | select(.type == "assistant") | .message.content[]? |
      select(.type == "tool_use" and .name == "Bash" and
        .input.command == "npm test") | .id]) as $test_ids |
    ($test_ids | length) >= 1 and
    ([.[] | select(.type == "user") as $event |
      $event.message.content[]? |
      select(.type == "tool_result" and
        ((.tool_use_id as $id | $test_ids | index($id)) != null) and
        ((.is_error // false) == false)) |
      $event.tool_use_result |
      select((.interrupted // false) == false and
        ((.stdout // "") | test("(pass [1-9]|# pass [1-9]|[1-9]+ passing)"; "i")))] |
      length) >= 1
  ' "$label"
}

SDD="$EVIDENCE_ROOT/subagent-driven-development/confirming-fable/explicit-transcript.jsonl"
jq_assert "$SDD" '
  ([.[] | select(.type == "assistant") | .message.content[]? |
    select(.type == "tool_use" and .name == "Agent") |
    {id, role: ((.input.description // "") + " " + (.input.prompt // ""))}]) as $agents |
  ($agents | map(select(.role | test("implementer"; "i"))) | length) >= 1 and
  ($agents | map(select(.role | test("task reviewer|review task"; "i"))) | length) >= 1 and
  ($agents | map(select(.role | test("whole.branch|final (code )?review|broad final review"; "i"))) | length) >= 1 and
  ($agents | map(.id) | unique | length) >= 3
' "explicit SDD uses distinct implementer, task-reviewer, and final-reviewer agents"
jq_assert "$SDD" '
  any(.[]; .type == "assistant" and
    any(.message.content[]?;
      .type == "tool_use" and .name == "Skill" and
      .input.skill == "superpowers:finishing-a-development-branch"))
' "explicit SDD invokes finishing-a-development-branch"
jq_assert "$SDD" '
  any(.[]; .type == "result" and
    ((.result // "") | test("1\\. Merge back to") and
      test("4\\. Discard this work") and test("Which option\\?")))
' "explicit SDD reaches the safe finishing menu handoff"
assert_direct_passing_npm_test "$SDD" "explicit SDD finishing handoff has an unmasked passing npm test result"
assert_safe_handoff "$SDD" "explicit SDD does not execute a finishing choice"
assert_clean_transcript "$SDD" "explicit SDD transcript has no module-type warning"

for mode in explicit standard; do
  transcript="$EVIDENCE_ROOT/executing-plans/confirming-fable/$mode/$mode-transcript.jsonl"
  jq_assert "$transcript" '
    any(.[]; .type == "assistant" and
      any(.message.content[]?;
        .type == "tool_use" and .name == "Skill" and
        .input.skill == "superpowers:executing-plans"))
  ' "$mode executing-plans invokes the selected skill"
  jq_assert "$transcript" '
    any(.[]; .type == "assistant" and
      any(.message.content[]?;
        .type == "tool_use" and .name == "Skill" and
        .input.skill == "superpowers:finishing-a-development-branch"))
  ' "$mode executing-plans invokes finishing-a-development-branch"
  jq_assert "$transcript" '
    ([.[] | select(.type == "assistant") | .message.content[]? |
      select(.type == "tool_use" and .name == "Bash" and
        .input.command == "./verify.sh") | .id]) as $verify_ids |
    ($verify_ids | length) >= 1 and
    ([.[] | select(.type == "user") |
      .message.content[]? |
      select(.type == "tool_result" and
        ((.tool_use_id as $id | $verify_ids | index($id)) != null) and
        ((.is_error // false) == false) and
        ((.content // "") | test("status verified")))] |
      length) >= 1
  ' "$mode executing-plans has an observable passing plan verification"
  status_path="$EVIDENCE_ROOT/executing-plans/confirming-fable/$mode/workspace/status.txt"
  if [[ -f "$status_path" ]] && [[ "$(<"$status_path")" == "ready" ]]; then
    pass "$mode executing-plans produces the planned ready state"
  else
    fail "$mode executing-plans produces the planned ready state"
  fi
  jq_assert "$transcript" '
    any(.[]; .type == "result" and
      ((.result // "") | test("1\\. Merge back to") and
        test("4\\. Discard this work") and test("Which option\\?")))
  ' "$mode executing-plans reaches the safe finishing menu handoff"
  assert_direct_passing_npm_test "$transcript" "$mode executing-plans finishing handoff has an unmasked passing npm test result"
  assert_safe_handoff "$transcript" "$mode executing-plans does not execute a finishing choice"
  assert_clean_transcript "$transcript" "$mode executing-plans transcript has no module-type warning"
done

for mode in explicit standard; do
  transcript="$EVIDENCE_ROOT/dispatching-parallel-agents/$mode-transcript.jsonl"
  jq_assert "$transcript" '
    any(.[]; .type == "assistant" and
      ([.message.content[]? |
        select(.type == "tool_use" and .name == "Agent") |
        ((.input.description // "") + " " + (.input.prompt // ""))]) as $batch |
      ($batch | length) == 3 and
      any($batch[]; test("alpha"; "i")) and
      any($batch[]; test("beta"; "i")) and
      any($batch[]; test("gamma"; "i")))
  ' "$mode parallel path dispatches three agents in one assistant tool batch"
  for result in alpha:3 beta:4 gamma:2; do
    name="${result%%:*}"
    expected="${result##*:}"
    result_path="$EVIDENCE_ROOT/dispatching-parallel-agents/$mode-workspace/$name.result"
    if [[ -f "$result_path" ]] && [[ "$(<"$result_path")" == "$expected" ]]; then
      pass "$mode parallel path produces verified $name result"
    else
      fail "$mode parallel path produces verified $name result"
    fi
  done
done

for scenario in red/automatic green/automatic green/explicit green/standard; do
  transcript="$EVIDENCE_ROOT/finishing-a-development-branch/$scenario-transcript.jsonl"
  assert_direct_passing_npm_test "$transcript" "$scenario finishing path has an unmasked passing npm test result"
  assert_safe_handoff "$transcript" "$scenario finishing path does not execute a menu choice"
  assert_clean_transcript "$transcript" "$scenario finishing transcript has no module-type warning"
done

jq_assert "$EVIDENCE_ROOT/finishing-a-development-branch/red/automatic-transcript.jsonl" '
  any(.[]; .type == "result" and
    ((.result // "") | test("DECISION: FULL") and
      test("1\\. Merge back to") and test("4\\. Discard this work")))
' "old automatic finishing path presents the full menu after verification"
jq_assert "$EVIDENCE_ROOT/finishing-a-development-branch/green/automatic-transcript.jsonl" '
  any(.[]; .type == "result" and
    ((.result // "") | test("DECISION: BYPASS") and
      (test("1\\. Merge back to") | not) and
      (test("4\\. Discard this work") | not)))
' "new automatic lean finishing path returns a concise handoff without the menu"
for mode in explicit standard; do
  transcript="$EVIDENCE_ROOT/finishing-a-development-branch/green/$mode-transcript.jsonl"
  jq_assert "$transcript" '
    any(.[]; .type == "result" and
      ((.result // "") | test("DECISION: FULL") and
        test("1\\. Merge back to") and test("4\\. Discard this work")))
  ' "$mode finishing positive path presents the full menu"
done

finish
