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

SAFE_HANDOFF_FILTER='
  def delivery_command:
    test(
      "(^|[;&|()][[:space:]]*)(?:(?:[[:alpha:]_][[:alnum:]_]*=[^[:space:];&|]+|command|sudo|env)[[:space:]]+)*git[^;&|\\n]*[[:space:]]+(?:push|merge)(?:[[:space:];&|]|$)|(^|[;&|()][[:space:]]*)(?:(?:[[:alpha:]_][[:alnum:]_]*=[^[:space:];&|]+|command|sudo|env)[[:space:]]+)*git[^;&|\\n]*[[:space:]]+branch[[:space:]]+(?:-[dD]|--delete)(?:[[:space:];&|]|$)|(^|[;&|()][[:space:]]*)(?:(?:[[:alpha:]_][[:alnum:]_]*=[^[:space:];&|]+|command|sudo|env)[[:space:]]+)*git[^;&|\\n]*[[:space:]]+worktree[[:space:]]+remove(?:[[:space:];&|]|$)|(^|[;&|()][[:space:]]*)gh[^;&|\\n]*[[:space:]]+pr[[:space:]]+create(?:[[:space:];&|]|$)|(^|[;&|()][[:space:]]*)hub[[:space:]]+pull-request(?:[[:space:];&|]|$)";
      "i"
    );
  def executed_choice_claim:
    test(
      "\\b(?:merged|pushed)\\b|pull request (?:was |has been )?(?:created|opened)|\\b(?:created|opened) (?:a )?(?:pull request|PR)\\b|\\b(?:kept|keeping) (?:the )?branch\\b|\\b(?:discarded|deleted) (?:the )?(?:branch|changes|worktree)\\b|\\b(?:cleaned up|removed) (?:the )?(?:branch|worktree)\\b|\\b(?:selected|chose|executed|completed) (?:option|choice)[[:space:]]*[1-4]\\b";
      "i"
    );
  ([.[] | select(.type == "assistant") | .message.content[]? |
    select(.type == "tool_use" and .name == "Bash") |
    .input.command |
    select(delivery_command)] | length) == 0 and
  ([.[] |
    if .type == "result" then .result // ""
    elif .type == "assistant" then
      .message.content[]? | select(.type == "text") | .text // ""
    else empty
    end |
    select(executed_choice_claim)] | length) == 0
'

DIRECT_PASSING_NPM_TEST_FILTER='
  def rendered_text:
    if type == "string" then .
    elif type == "array" then
      map(if type == "string" then . elif .text? then .text else tostring end) |
      join("\n")
    elif . == null then ""
    else tostring
    end;
  def zero_exit_if_exposed:
    ((has("exitCode") | not) or (.exitCode | tostring) == "0") and
    ((has("exit_code") | not) or (.exit_code | tostring) == "0") and
    ((has("code") | not) or (.code | tostring) == "0") and
    ((has("signal") | not) or .signal == null);
  def passing_output:
    . as $output |
    ($output | test("(# pass[[:space:]]+[1-9][0-9]*|[1-9][0-9]* passing|[1-9][0-9]* passed)"; "i")) and
    ($output | test("(^|\n)[[:space:]]*#[[:space:]]*fail[[:space:]]+0([[:space:]]|$)|(^|\n)[^\n]*\\b0 (?:failed|failures)\\b"; "i")) and
    (($output | gsub("\\b0[[:space:]]+(?:failed|failures)\\b"; ""; "i")) |
      test("(^|\n)[[:space:]]*not ok\\b|#[[:space:]]*fail[[:space:]]+[1-9][0-9]*\\b|\\bfailed\\b|\\berror\\b|npm ERR!"; "i") | not);
  ([.[] | select(.type == "assistant") | .message.content[]? |
    select(.type == "tool_use" and .name == "Bash" and
      .input.command == "npm test") | .id]) as $test_ids |
  ($test_ids | length) >= 1 and
  ([.[] | select(.type == "user") as $event |
    $event.message.content[]? |
    select(.type == "tool_result" and
      ((.tool_use_id as $id | $test_ids | index($id)) != null) and
      ((.is_error // false) == false)) as $result |
    ($event.tool_use_result // {}) as $execution |
    select(
      (($execution.interrupted // false) == false) and
      (($execution.is_error // false) == false) and
      ($execution | zero_exit_if_exposed)
    ) |
    (
      (($result.content // "") | rendered_text) + "\n" +
      (($execution.stdout // "") | rendered_text) + "\n" +
      (($execution.stderr // "") | rendered_text)
    ) |
    select(passing_output)] |
    length) >= 1
'

PARALLEL_BATCH_FILTER='
  . as $events |
  ([
    $events[] |
    select(.type == "assistant" and .message.id != null)
  ] | group_by(.message.id) | map({
    message_id: .[0].message.id,
    agents: [
      .[] | .message.content[]? |
      select(.type == "tool_use" and .name == "Agent")
    ]
  }) | map(select(
    (.agents | length) == 3 and
    (.agents | map(.id) | unique | length) == 3 and
    (.agents | all(.input.run_in_background == true)) and
    any(.agents[]; ((.input.description // "") + " " + (.input.prompt // "")) | test("alpha"; "i")) and
    any(.agents[]; ((.input.description // "") + " " + (.input.prompt // "")) | test("beta"; "i")) and
    any(.agents[]; ((.input.description // "") + " " + (.input.prompt // "")) | test("gamma"; "i"))
  ))) as $batches |
  any($batches[];
    . as $batch |
    ($batch.agents | map(.id)) as $agent_ids |
    ([
      $events | to_entries[] |
      select(
        .value.type == "system" and
        .value.subtype == "task_started" and
        ((.value.tool_use_id as $id | $agent_ids | index($id)) != null)
      ) |
      {index: .key, task_id: .value.task_id, tool_use_id: .value.tool_use_id}
    ]) as $starts |
    ([
      $events | to_entries[] |
      select(
        (.value.type == "system" and .value.subtype == "task_notification") or
        (.value.type == "assistant" and any(.value.message.content[]?;
          .type == "tool_use" and
          (.name | test("wait|join|taskoutput|schedulewakeup"; "i"))
        ))
      ) |
      .key
    ] | first) as $first_wait_or_notification |
    ([
      $events[] |
      select(
        .type == "system" and
        .subtype == "task_notification" and
        .status == "completed" and
        ((.tool_use_id as $id | $agent_ids | index($id)) != null)
      ) |
      {task_id, tool_use_id}
    ]) as $completions |
    ($starts | length) == 3 and
    ($starts | map(.tool_use_id) | unique | length) == 3 and
    $first_wait_or_notification != null and
    all($starts[]; .index < $first_wait_or_notification) and
    ($completions | length) == 3 and
    all($starts[];
      . as $start |
      any($completions[];
        .tool_use_id == $start.tool_use_id and
        .task_id == $start.task_id
      )
    )
  )
'

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
  jq_assert "$transcript" "$SAFE_HANDOFF_FILTER" "$label"
}

assert_direct_passing_npm_test() {
  local transcript="$1" label="$2"
  jq_assert "$transcript" "$DIRECT_PASSING_NPM_TEST_FILTER" "$label"
}

assert_validator_self_tests() {
  local command
  for command in \
    'git -C /tmp/repo push origin feature' \
    'git -C "/tmp/repo with spaces" push origin feature' \
    'git --git-dir=/tmp/repo/.git merge feature' \
    'git --work-tree /tmp/repo branch -D feature' \
    'GIT_DIR=/tmp/repo/.git git push origin feature' \
    'sudo git -C /tmp/repo merge feature' \
    'gh --repo owner/repo pr create' \
    'hub pull-request'; do
    if jq -n -e --arg command "$command" \
      '[{type:"assistant",message:{content:[{type:"tool_use",name:"Bash",input:{command:$command}}]}}] |
      '"$SAFE_HANDOFF_FILTER" >/dev/null; then
      printf 'validator self-test accepted delivery command: %s\n' "$command" >&2
      exit 1
    fi
  done

  if ! jq -n -e \
    '[{type:"result",result:"Choose one: Merge back, Push and create a PR, Keep the branch, or Discard this work."}] |
    '"$SAFE_HANDOFF_FILTER" >/dev/null; then
    printf 'validator self-test rejected prose-only menu presentation\n' >&2
    exit 1
  fi

  if jq -n -e \
    '[{type:"result",result:"I selected option 2 and pushed the branch."}] |
    '"$SAFE_HANDOFF_FILTER" >/dev/null; then
    printf 'validator self-test accepted an executed-choice claim\n' >&2
    exit 1
  fi

  local npm_fixture='
    [{type:"assistant",message:{content:[
      {type:"tool_use",id:"test-id",name:"Bash",input:{command:"npm test"}}
    ]}},
    {type:"user",message:{content:[
      {type:"tool_result",tool_use_id:"test-id",is_error:false,content:$output}
    ]},tool_use_result:{
      stdout:$output,stderr:"",interrupted:$interrupted,exitCode:$exit_code
    }}] |
  '
  if ! jq -n -e \
    --arg output $'TAP version 13\n# pass 1\n# fail 0' \
    --argjson interrupted false --argjson exit_code 0 \
    "$npm_fixture$DIRECT_PASSING_NPM_TEST_FILTER" >/dev/null; then
    printf 'validator self-test rejected a clean passing npm result\n' >&2
    exit 1
  fi

  local bad_output
  for bad_output in \
    $'TAP version 13\n# pass 1' \
    $'TAP version 13\n# pass 1\n# fail 2\nnot ok 2 - broken' \
    $'1 passing\n0 failures\nERROR: teardown failed'; do
    if jq -n -e \
      --arg output "$bad_output" \
      --argjson interrupted false --argjson exit_code 0 \
      "$npm_fixture$DIRECT_PASSING_NPM_TEST_FILTER" >/dev/null; then
      printf 'validator self-test accepted an invalid npm result\n' >&2
      exit 1
    fi
  done

  if jq -n -e \
    --arg output $'TAP version 13\n# pass 1\n# fail 0' \
    --argjson interrupted false --argjson exit_code 1 \
    "$npm_fixture$DIRECT_PASSING_NPM_TEST_FILTER" >/dev/null; then
    printf 'validator self-test accepted a nonzero npm exit\n' >&2
    exit 1
  fi
}

assert_validator_self_tests

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
  jq_assert "$transcript" "$PARALLEL_BATCH_FILTER" \
    "$mode parallel path dispatches three background agents concurrently in one logical message"
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
