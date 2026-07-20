#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: run-live-mode-test.sh <claude|codex> <model> <case>\n' >&2
  exit 2
}

[[ $# -eq 3 ]] || usage
BACKEND="$1"
MODEL="$2"
CASE="$3"

case "$BACKEND" in
  claude|codex) ;;
  *) printf 'unknown backend: %s\n' "$BACKEND" >&2; exit 2 ;;
esac
case "$CASE" in
  lean|standard|strict|override|escalation|explicit-skill) ;;
  *) printf 'unknown case: %s\n' "$CASE" >&2; exit 2 ;;
esac
case "$MODEL" in
  *[!A-Za-z0-9._-]*|'')
    printf 'model contains unsafe path characters: %s\n' "$MODEL" >&2
    exit 2
    ;;
esac

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROMPT_FILE="$ROOT/tests/workflow-modes/cases/$CASE.txt"
VALIDATOR="$ROOT/tests/workflow-modes/assert-live-mode-result.py"
TIMEOUT_RUNNER="$ROOT/tests/workflow-modes/run-with-timeout.py"
PLUGIN_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/.codex-plugin/plugin.json")"
EVAL_ROOT="${ADAPTIVE_MODE_EVAL_ROOT:-/tmp/superpowers-mode-evals}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM:-0}"
OUT_DIR="$EVAL_ROOT/$BACKEND/$MODEL/$CASE/$RUN_ID"
PROJECT="$OUT_DIR/project"
LOG="$OUT_DIR/transcript.jsonl"
STDERR_LOG="$OUT_DIR/stderr.log"
ASSISTANT_TEXT="$OUT_DIR/assistant.txt"
POSTCHECK_LOG="$OUT_DIR/postcheck.log"
BACKEND_COMMAND="$OUT_DIR/backend-command.json"
TIMEOUT_SECONDS="${ADAPTIVE_MODE_EVAL_TIMEOUT_SECONDS:-900}"
TERM_GRACE_SECONDS="${ADAPTIVE_MODE_EVAL_TERM_GRACE_SECONDS:-2}"

for command_name in git python3; do
  command -v "$command_name" >/dev/null || {
    printf 'required command not found: %s\n' "$command_name" >&2
    exit 2
  }
done
[[ -f "$PROMPT_FILE" ]] || {
  printf 'prompt file not found: %s\n' "$PROMPT_FILE" >&2
  exit 2
}
[[ -f "$VALIDATOR" ]] || {
  printf 'validator not found: %s\n' "$VALIDATOR" >&2
  exit 2
}
[[ -f "$TIMEOUT_RUNNER" ]] || {
  printf 'timeout runner not found: %s\n' "$TIMEOUT_RUNNER" >&2
  exit 2
}

mkdir -p "$PROJECT"
git -C "$PROJECT" init -q -b main
git -C "$PROJECT" config user.name "Mode Eval"
git -C "$PROJECT" config user.email "mode-eval@example.invalid"

case "$CASE" in
  lean)
    printf 'This is teh demo.\n' >"$PROJECT/README.md"
    ;;
  standard)
    mkdir -p "$PROJECT/src" "$PROJECT/test"
    printf '%s\n' '[{"price":2},{"price":3}]' >"$PROJECT/items.json"
    printf '%s\n' '#!/usr/bin/env node' 'console.log("usage: cli summary")' >"$PROJECT/src/cli.js"
    printf '%s\n' '{"scripts":{"test":"node --test"}}' >"$PROJECT/package.json"
    ;;
  strict)
    printf '%s\n' '# payment migration fixture' >"$PROJECT/README.md"
    ;;
  override)
    mkdir -p "$PROJECT/src" "$PROJECT/test"
    printf '%s\n' 'export const accepts = token => Boolean(token);' >"$PROJECT/src/auth.js"
    printf '%s\n' '{"type":"module","scripts":{"test":"node --test"}}' >"$PROJECT/package.json"
    ;;
  escalation)
    mkdir -p "$PROJECT/src"
    printf '%s\n' \
      '// Production payment schema consumed by the public billing API.' \
      'export const payment = { amount: 10 };' >"$PROJECT/src/schema.js"
    printf '%s\n' \
      'import { payment } from "./schema.js";' \
      'export const publicPaymentResponse = () => ({ amount: payment.amount });' >"$PROJECT/src/billing.js"
    ;;
  explicit-skill)
    mkdir -p "$PROJECT/src"
    printf '%s\n' 'export const greet = name => `Hello ${name}`;' >"$PROJECT/src/greeting.js"
    ;;
esac

git -C "$PROJECT" add .
git -C "$PROJECT" commit -q -m fixture
BASE_SHA="$(git -C "$PROJECT" rev-parse HEAD)"
PROMPT="$(<"$PROMPT_FILE")"

run_with_timeout() {
  local seconds="$1" stdout_file="$2" stderr_file="$3"
  shift 3
  python3 "$TIMEOUT_RUNNER" "$seconds" "$TERM_GRACE_SECONDS" \
    "$stdout_file" "$stderr_file" "$@"
}

record_backend_command() {
  python3 - "$BACKEND_COMMAND" "$@" <<'PY'
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:], indent=2) + "\n")
PY
}

verify_codex_home() {
  local home="$1" list_file="$2"
  env CODEX_HOME="$home" codex plugin list --json >"$list_file"
  python3 - "$ROOT" "$home" "$list_file" <<'PY'
import filecmp
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
home = pathlib.Path(sys.argv[2]).resolve()
listing = json.loads(pathlib.Path(sys.argv[3]).read_text())
expected_version = json.loads((root / ".codex-plugin/plugin.json").read_text())["version"]
matches = [
    plugin
    for plugin in listing.get("installed", [])
    if plugin.get("pluginId") == "superpowers@superpowers-dev"
    and plugin.get("enabled") is True
]
if len(matches) != 1:
    raise SystemExit(
        "dedicated CODEX_HOME must enable exactly one "
        "superpowers@superpowers-dev local plugin"
    )
plugin = matches[0]
if plugin.get("version") != expected_version:
    raise SystemExit(
        f"dedicated plugin version {plugin.get('version')!r} != checkout {expected_version!r}"
    )
source = plugin.get("marketplaceSource", {}).get("source")
if not source or pathlib.Path(source).resolve() != root:
    raise SystemExit(f"dedicated plugin marketplace source {source!r} != checkout {str(root)!r}")
installed = home / "plugins/cache/superpowers-dev/superpowers" / expected_version
if not installed.is_dir():
    raise SystemExit(f"dedicated plugin cache missing: {installed}")
for relative in (
    "skills/selecting-workflow-mode/SKILL.md",
    "skills/selecting-workflow-mode/references/risk-matrix.md",
    "skills/using-superpowers/SKILL.md",
):
    source_file = root / relative
    installed_file = installed / relative
    if not installed_file.is_file() or not filecmp.cmp(source_file, installed_file, shallow=False):
        raise SystemExit(f"dedicated plugin is stale or mismatched: {relative}")
PY
}

verify_codex_model() {
  local home="$1" model="$2" catalog_file="$3"
  env CODEX_HOME="$home" codex debug models >"$catalog_file"
  python3 - "$model" "$catalog_file" <<'PY'
import json
import pathlib
import sys

expected = sys.argv[1]
catalog = json.loads(pathlib.Path(sys.argv[2]).read_text())
models = catalog.get("models", []) if isinstance(catalog, dict) else catalog
matches = [model for model in models if isinstance(model, dict) and model.get("slug") == expected]
if len(matches) != 1:
    raise SystemExit(f"Codex model catalog must contain exact slug {expected!r}; found {len(matches)}")
PY
}

BACKEND_STATUS=0
case "$BACKEND" in
  claude)
    command -v claude >/dev/null || {
      printf 'claude not found in PATH\n' >&2
      exit 2
    }
    (
      cd "$PROJECT"
      record_backend_command claude -p "$PROMPT" \
        --plugin-dir "$ROOT" \
        --setting-sources project \
        --strict-mcp-config \
        --mcp-config '{"mcpServers":{}}' \
        --model "$MODEL" \
        --dangerously-skip-permissions \
        --max-turns 20 \
        --output-format stream-json \
        --verbose \
        --no-session-persistence
      run_with_timeout "$TIMEOUT_SECONDS" "$LOG" "$STDERR_LOG" \
        claude -p "$PROMPT" \
        --plugin-dir "$ROOT" \
        --setting-sources project \
        --strict-mcp-config \
        --mcp-config '{"mcpServers":{}}' \
        --model "$MODEL" \
        --dangerously-skip-permissions \
        --max-turns 20 \
        --output-format stream-json \
        --verbose \
        --no-session-persistence
    ) || BACKEND_STATUS=$?
    ;;
  codex)
    command -v codex >/dev/null || {
      printf 'codex not found in PATH\n' >&2
      exit 2
    }
    : "${ADAPTIVE_CODEX_HOME:?set ADAPTIVE_CODEX_HOME to an isolated Codex home with this fork installed}"
    CODEX_PREFLIGHT="$OUT_DIR/codex-plugin-list.json"
    CODEX_MODEL_CATALOG="$OUT_DIR/codex-model-catalog.json"
    verify_codex_home "$ADAPTIVE_CODEX_HOME" "$CODEX_PREFLIGHT"
    verify_codex_model "$ADAPTIVE_CODEX_HOME" "$MODEL" "$CODEX_MODEL_CATALOG"
    record_backend_command env CODEX_HOME="$ADAPTIVE_CODEX_HOME" codex exec \
      --model "$MODEL" \
      --cd "$PROJECT" \
      --sandbox workspace-write \
      --ephemeral \
      --ignore-rules \
      --json \
      "$PROMPT"
    run_with_timeout "$TIMEOUT_SECONDS" "$LOG" "$STDERR_LOG" \
      env CODEX_HOME="$ADAPTIVE_CODEX_HOME" codex exec \
      --model "$MODEL" \
      --cd "$PROJECT" \
      --sandbox workspace-write \
      --ephemeral \
      --ignore-rules \
      --json \
      "$PROMPT" || BACKEND_STATUS=$?
    ;;
esac

if [[ "$BACKEND_STATUS" -ne 0 ]]; then
  printf 'backend failed with status %s\nTranscript: %s\nStderr: %s\n' \
    "$BACKEND_STATUS" "$LOG" "$STDERR_LOG" >&2
  if [[ -s "$STDERR_LOG" ]]; then
    sed -n '1,80p' "$STDERR_LOG" >&2
  fi
  exit "$BACKEND_STATUS"
fi

if ! python3 "$VALIDATOR" "$BACKEND" "$MODEL" "$CASE" "$LOG" \
  "$ASSISTANT_TEXT" "$ROOT" "$PLUGIN_VERSION"; then
  printf 'Transcript: %s\nAssistant: %s\nStderr: %s\nProject: %s\n' \
    "$LOG" "$ASSISTANT_TEXT" "$STDERR_LOG" "$PROJECT" >&2
  exit 1
fi

postcheck() {
  has_regression_check() {
    find "$PROJECT" -type f \
      \( -path '*/test/*' -o -path '*/tests/*' -o -name '*.test.*' -o -name '*.spec.*' \) \
      ! -path '*/node_modules/*' -print 2>/dev/null | grep -q .
  }

  repository_unchanged() {
    [[ "$(git -C "$PROJECT" rev-parse HEAD)" == "$BASE_SHA" ]] || return 1
    git -C "$PROJECT" diff --quiet "$BASE_SHA" -- || return 1
    [[ -z "$(git -C "$PROJECT" status --porcelain --untracked-files=all)" ]]
  }

  case "$CASE" in
    lean)
      grep -Fqx 'This is the demo.' "$PROJECT/README.md" || return 1
      [[ ! -e "$PROJECT/docs/superpowers" ]] || return 1
      [[ ! -e "$PROJECT/.worktrees" ]] || return 1
      ;;
    standard)
      has_regression_check || return 1
      ! grep -Eqi 'looks right so far|approve the design|should I continue' "$ASSISTANT_TEXT" || return 1
      [[ ! -e "$PROJECT/docs/superpowers/specs" ]] || return 1
      [[ ! -e "$PROJECT/.worktrees" ]] || return 1
      (
        cd "$PROJECT"
        npm test --silent
        node src/cli.js summary >"$OUT_DIR/summary.json"
      ) || return 1
      python3 - "$OUT_DIR/summary.json" <<'PY'
import json
import pathlib
import sys

lines = [line for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if line.strip()]
if not lines:
    raise SystemExit("summary command produced no output")
summary = json.loads(lines[-1])
if summary.get("count") != 2 or summary.get("total") != 5:
    raise SystemExit(f"unexpected summary output: {summary!r}")
PY
      ;;
    strict)
      repository_unchanged || return 1
      grep -q '?' "$ASSISTANT_TEXT" || return 1
      ;;
    override)
      has_regression_check || return 1
      grep -Eq 'expires|expir|\.exp([^[:alnum:]_]|$)' "$PROJECT/src/auth.js" || return 1
      (
        cd "$PROJECT"
        npm test --silent
      ) || return 1
      ;;
    escalation|explicit-skill)
      repository_unchanged || return 1
      ;;
  esac
}

if ! postcheck >"$POSTCHECK_LOG" 2>&1; then
  printf 'case artifact assertions failed\nPostcheck: %s\n' "$POSTCHECK_LOG" >&2
  sed -n '1,120p' "$POSTCHECK_LOG" >&2
  exit 1
fi

printf 'PASS %s %s %s\nRun: %s\nTranscript: %s\nAssistant: %s\n' \
  "$BACKEND" "$MODEL" "$CASE" "$OUT_DIR" "$LOG" "$ASSISTANT_TEXT"
