#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER="$ROOT/tests/workflow-modes/run-live-mode-test.sh"
PLUGIN_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.codex-plugin/plugin.json")"
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
    text = "Mode: strict — production payment migration and public API change.\nWhich rollback requirement applies to this migration?"
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
    text = "Promoting to strict — inspection found src/schema.js defines the amount field consumed by src/billing.js as part of the public payment API; renaming it would break compatibility.\nShould we retain the compatibility alias for existing API clients?"
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
        "plugins": [{
            "name": "superpowers",
            "path": os.environ["EXPECTED_PLUGIN_ROOT"],
            "source": "superpowers@inline",
            "version": os.environ["EXPECTED_PLUGIN_VERSION"],
        }],
    },
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}},
    {"type": "result", "subtype": "success", "result": text},
]
if case == "escalation":
    declaration = "Mode: standard — bounded rename pending repository inspection."
    events[1:2] = [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": declaration}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{
            "type": "tool_use",
            "id": "inspection",
            "name": "Read",
            "input": {"file_path": str(project / "src/schema.js")},
        }]}},
        {"type": "user", "message": {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": "inspection",
            "is_error": False,
            "content": "schema inspected",
        }]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}},
    ]
    if os.environ.get("STUB_ESCALATION_MUTATION") == "1":
        events.insert(3, {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{
                "type": "tool_use",
                "id": "mutation",
                "name": "Write",
                "input": {"file_path": str(project / "src/schema.js")},
            }]},
        })
if os.environ.get("STUB_NO_MODE") == "1":
    events[1]["message"]["content"][0]["text"] = "Finished and verified without a declaration."
for event in events:
    print(json.dumps(event))
STUB
chmod +x "$TEST_TMP/bin/claude"

cat >"$TEST_TMP/bin/codex" <<'STUB'
#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
if args == ["plugin", "list", "--json"]:
    plugin_id = "wrong@plugin" if os.environ.get("STUB_BAD_PLUGIN_SLUG") == "1" else "superpowers@superpowers-dev"
    source = "/wrong/source" if os.environ.get("STUB_BAD_PLUGIN_SOURCE") == "1" else os.environ["EXPECTED_PLUGIN_ROOT"]
    version = "wrong-version" if os.environ.get("STUB_BAD_PLUGIN_VERSION") == "1" else os.environ["EXPECTED_PLUGIN_VERSION"]
    print(json.dumps({"installed": [{
        "pluginId": plugin_id,
        "enabled": True,
        "version": version,
        "marketplaceSource": {"source": source},
    }]}))
elif args == ["debug", "models"]:
    slug = "different-model" if os.environ.get("STUB_MISSING_MODEL") == "1" else "test-model"
    print(json.dumps({"models": [{"slug": slug, "display_name": slug}]}))
elif args and args[0] == "exec":
    pathlib.Path(os.environ["CODEX_ARGV_LOG"]).write_text(json.dumps(args))
    model = args[args.index("--model") + 1]
    if model != "test-model":
        raise SystemExit(19)
    project = pathlib.Path(args[args.index("--cd") + 1])
    (project / "README.md").write_text("This is the demo.\n")
    events = [
        {"type": "thread.started", "thread_id": "thread"},
        {"type": "item.completed", "item": {
            "id": "message", "type": "agent_message",
            "text": "Mode: lean — localized typo correction.\nVerification passed.",
        }},
        {"type": "turn.completed", "usage": {}},
    ]
    for event in events:
        print(json.dumps(event))
else:
    raise SystemExit(f"unexpected codex args: {args!r}")
STUB
chmod +x "$TEST_TMP/bin/codex"

CODEX_HOME="$TEST_TMP/codex-home"
CODEX_CACHE="$CODEX_HOME/plugins/cache/superpowers-dev/superpowers/$PLUGIN_VERSION"
mkdir -p "$CODEX_CACHE/skills/selecting-workflow-mode/references" \
  "$CODEX_CACHE/skills/using-superpowers"
cp "$ROOT/skills/selecting-workflow-mode/SKILL.md" \
  "$CODEX_CACHE/skills/selecting-workflow-mode/SKILL.md"
cp "$ROOT/skills/selecting-workflow-mode/references/risk-matrix.md" \
  "$CODEX_CACHE/skills/selecting-workflow-mode/references/risk-matrix.md"
cp "$ROOT/skills/using-superpowers/SKILL.md" \
  "$CODEX_CACHE/skills/using-superpowers/SKILL.md"

for case_name in lean standard strict override escalation explicit-skill; do
  output="$({
    PATH="$TEST_TMP/bin:$PATH" \
      EXPECTED_PLUGIN_ROOT="$ROOT" \
      EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
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

cp "$CODEX_CACHE/skills/selecting-workflow-mode/SKILL.md" \
  "$TEST_TMP/selector-skill.backup"
printf '\n# stale test copy\n' >>"$CODEX_CACHE/skills/selecting-workflow-mode/SKILL.md"
hash_output="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
    CODEX_ARGV_LOG="$TEST_TMP/codex-hash-argv.json" \
    ADAPTIVE_CODEX_HOME="$CODEX_HOME" \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/bad-hash-evals" \
    "$RUNNER" codex test-model lean
} 2>&1)" && {
  printf 'expected stale plugin hash to fail preflight\n' >&2
  exit 1
}
[[ "$hash_output" == *"stale or mismatched"* ]] || {
  printf 'stale plugin failure was not explicit:\n%s\n' "$hash_output" >&2
  exit 1
}
cp "$TEST_TMP/selector-skill.backup" \
  "$CODEX_CACHE/skills/selecting-workflow-mode/SKILL.md"

codex_output="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
    CODEX_ARGV_LOG="$TEST_TMP/codex-argv.json" \
    ADAPTIVE_CODEX_HOME="$CODEX_HOME" \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/codex-evals" \
    "$RUNNER" codex test-model lean
} 2>&1)" || {
  printf '%s\n' "$codex_output"
  exit 1
}
[[ "$codex_output" == *"PASS codex test-model lean"* ]] || {
  printf 'missing Codex PASS:\n%s\n' "$codex_output" >&2
  exit 1
}
python3 - "$TEST_TMP/codex-argv.json" <<'PY'
import json
import pathlib
import sys

args = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert args[args.index("--model") + 1] == "test-model", args
PY
find "$TEST_TMP/codex-evals" -name codex-model-catalog.json -type f | grep -q . || {
  printf 'Codex model catalog evidence was not preserved\n' >&2
  exit 1
}

missing_model_output="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
    CODEX_ARGV_LOG="$TEST_TMP/codex-missing-argv.json" \
    STUB_MISSING_MODEL=1 \
    ADAPTIVE_CODEX_HOME="$CODEX_HOME" \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/missing-model-evals" \
    "$RUNNER" codex test-model lean
} 2>&1)" && {
  printf 'expected unavailable exact Codex model to fail preflight\n' >&2
  exit 1
}
[[ "$missing_model_output" == *"exact slug 'test-model'"* ]] || {
  printf 'missing model failure was not explicit:\n%s\n' "$missing_model_output" >&2
  exit 1
}

for bad_plugin in STUB_BAD_PLUGIN_SLUG STUB_BAD_PLUGIN_SOURCE STUB_BAD_PLUGIN_VERSION; do
  plugin_output="$({
    env PATH="$TEST_TMP/bin:$PATH" \
      EXPECTED_PLUGIN_ROOT="$ROOT" \
      EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
      CODEX_ARGV_LOG="$TEST_TMP/codex-plugin-argv.json" \
      "$bad_plugin=1" \
      ADAPTIVE_CODEX_HOME="$CODEX_HOME" \
      ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/bad-plugin-evals" \
      "$RUNNER" codex test-model lean
  } 2>&1)" && {
    printf 'expected %s to fail plugin preflight\n' "$bad_plugin" >&2
    exit 1
  }
  [[ "$plugin_output" == *"dedicated"* ]] || {
    printf '%s failure was not explicit:\n%s\n' "$bad_plugin" "$plugin_output" >&2
    exit 1
  }
done

failure_output="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
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
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
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
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
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

escalation_order_failure="$({
  PATH="$TEST_TMP/bin:$PATH" \
    EXPECTED_PLUGIN_ROOT="$ROOT" \
    EXPECTED_PLUGIN_VERSION="$PLUGIN_VERSION" \
    STUB_ESCALATION_MUTATION=1 \
    ADAPTIVE_MODE_EVAL_ROOT="$TEST_TMP/escalation-order-evals" \
    "$RUNNER" claude test-model escalation
} 2>&1)" && {
  printf 'expected pre-promotion escalation mutation to fail\n' >&2
  exit 1
}
[[ "$escalation_order_failure" == *"mutation before strict promotion/approval pause"* ]] || {
  printf 'escalation ordering failure was not explicit:\n%s\n' \
    "$escalation_order_failure" >&2
  exit 1
}

run_count="$(find "$TEST_TMP/evals/claude/test-model" -name transcript.jsonl -type f | wc -l | tr -d ' ')"
[[ "$run_count" == 6 ]] || {
  printf 'expected six preserved transcripts; found %s\n' "$run_count" >&2
  exit 1
}

printf 'PASS live runner six-case fixture contract\n'
