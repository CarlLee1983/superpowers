#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER="$ROOT/tests/workflow-modes/run-live-mode-test.sh"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT
mkdir -p "$TEST_TMP/bin"

cat >"$TEST_TMP/bin/claude" <<'STUB'
#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys

args = sys.argv[1:]
prompt = args[args.index("-p") + 1]
model = args[args.index("--model") + 1]
project = pathlib.Path.cwd()

if 'typo "teh"' in prompt:
    case = "lean"
    if os.environ.get("STUB_BAD_ARTIFACT") != "1":
        (project / "README.md").write_text("This is the demo.\n")
    text = "Mode: lean — localized typo correction.\nVerified with an exact content check."
elif "JSON summary command" in prompt:
    case = "standard"
    (project / "test").mkdir(exist_ok=True)
    (project / "src/cli.js").write_text(
        '#!/usr/bin/env node\n'
        'const fs = require("node:fs");\n'
        'const items = JSON.parse(fs.readFileSync("items.json", "utf8"));\n'
        'console.log(JSON.stringify({count: items.length, total: items.reduce((n, item) => n + item.price, 0)}));\n'
    )
    (project / "test/summary.test.js").write_text(
        'const test = require("node:test");\n'
        'const assert = require("node:assert");\n'
        'test("fixture", () => assert.equal(2 + 3, 5));\n'
    )
    text = "Mode: standard — bounded CLI behavior and coverage.\nTests passed and output verified."
elif "production data migration" in prompt:
    case = "strict"
    if os.environ.get("STUB_COMMIT_ARTIFACT") == "1":
        (project / "design.md").write_text("unapproved design\n")
        subprocess.run(["git", "add", "design.md"], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "premature design"],
            check=True,
            capture_output=True,
        )
    text = "Mode: strict — production payment migration and public API change.\nBefore the design, which rollback constraints apply?"
elif "authentication sample" in prompt:
    case = "override"
    (project / "src/auth.js").write_text(
        'export const accepts = token => Boolean(token) && token.exp > Date.now() / 1000;\n'
    )
    (project / "src/auth.test.js").write_text(
        'import test from "node:test";\n'
        'import assert from "node:assert/strict";\n'
        'import { accepts } from "./auth.js";\n'
        'test("expired", () => assert.equal(accepts({exp: 0}), false));\n'
    )
    text = "Mode: lean — explicit override.\nWarning: authentication is security-sensitive; I will remain lean as requested. Verification passed."
elif "Rename the amount field" in prompt:
    case = "escalation"
    text = "Mode: strict — production payment API risk discovered during inspection.\nI am promoting the workflow because this public billing API requires design clarification."
elif "brainstorming skill" in prompt:
    case = "explicit-skill"
    text = "Mode: lean — explicit override.\nI am using the brainstorming skill. Two options are welcomeUser and greetUser."
else:
    raise SystemExit("unknown prompt")

events = [
    {
        "type": "system",
        "subtype": "init",
        "model": model,
        "permissionMode": "bypassPermissions",
        "plugins": [{"name": "superpowers", "path": os.environ["EXPECTED_PLUGIN_ROOT"]}],
    },
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}},
    {"type": "result", "subtype": "success", "result": text},
]
if os.environ.get("STUB_NO_MODE") == "1":
    events[1]["message"]["content"][0]["text"] = "Finished and verified without a declaration."
for event in events:
    print(json.dumps(event))
STUB
chmod +x "$TEST_TMP/bin/claude"

for case_name in lean standard strict override escalation explicit-skill; do
  output="$({
    PATH="$TEST_TMP/bin:$PATH" \
      EXPECTED_PLUGIN_ROOT="$ROOT" \
      ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/evals" \
      "$RUNNER" claude test-model "$case_name"
  } 2>&1)" || {
    printf '%s\n' "$output"
    exit 1
  }
  [[ "$output" == *"PASS claude test-model $case_name"* ]] || {
    printf 'missing PASS for %s\n%s\n' "$case_name" "$output" >&2
    exit 1
  }
done

failure_output="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    STUB_NO_MODE=1 \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/failing-evals" \
    "$RUNNER" claude test-model lean
} 2>&1)" && {
  printf 'expected missing declaration fixture to fail\n' >&2
  exit 1
}
[[ "$failure_output" == *"Transcript:"* && "$failure_output" == *"Assistant:"* ]] || {
  printf 'failure output omitted preserved evidence paths:\n%s\n' "$failure_output" >&2
  exit 1
}

artifact_failure="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    STUB_BAD_ARTIFACT=1 \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/bad-artifact-evals" \
    "$RUNNER" claude test-model lean
} 2>&1)" && {
  printf 'expected unchanged lean fixture to fail artifact checks\n' >&2
  exit 1
}
[[ "$artifact_failure" == *"case artifact assertions failed"* ]] || {
  printf 'bad artifact failure was not reported clearly:\n%s\n' "$artifact_failure" >&2
  exit 1
}

committed_artifact_failure="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    STUB_COMMIT_ARTIFACT=1 \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/committed-artifact-evals" \
    "$RUNNER" claude test-model strict
} 2>&1)" && {
  printf 'expected committed strict artifact to fail pause checks\n' >&2
  exit 1
}
[[ "$committed_artifact_failure" == *"case artifact assertions failed"* ]] || {
  printf 'committed strict artifact failure was not reported clearly:\n%s\n' "$committed_artifact_failure" >&2
  exit 1
}

run_count="$(find "$TEST_TMP/evals/claude/test-model" -name transcript.jsonl -type f | wc -l | tr -d ' ')"
[[ "$run_count" == 6 ]] || {
  printf 'expected six preserved transcripts; found %s\n' "$run_count" >&2
  exit 1
}

printf 'PASS live runner six-case fixture contract\n'
