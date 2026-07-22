#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_COMMAND="${CODEX_BIN:-codex}"
SESSION_MODEL=""

case "$#" in
  0)
    ;;
  2)
    if [[ "$1" != "--session" || -z "$2" ]]; then
      printf 'usage: smoke-codex-install.sh [--session MODEL]\n' >&2
      exit 2
    fi
    SESSION_MODEL="$2"
    ;;
  *)
    printf 'usage: smoke-codex-install.sh [--session MODEL]\n' >&2
    exit 2
    ;;
esac

if [[ "$CODEX_COMMAND" == */* ]]; then
  [[ -x "$CODEX_COMMAND" ]] || {
    printf 'error: Codex executable is unavailable: %s\n' "$CODEX_COMMAND" >&2
    exit 2
  }
else
  command -v "$CODEX_COMMAND" >/dev/null || {
    printf 'error: Codex executable is unavailable: %s\n' "$CODEX_COMMAND" >&2
    exit 2
  }
fi

SMOKE_ROOT="$(mktemp -d)"
cleanup() {
  rm -rf "$SMOKE_ROOT"
}
trap cleanup EXIT

CODEX_HOME="$SMOKE_ROOT/codex-home"
PROJECT="$SMOKE_ROOT/project"
PLUGIN_LIST="$SMOKE_ROOT/plugin-list.json"
TRANSCRIPT="$SMOKE_ROOT/session.jsonl"
mkdir -p "$CODEX_HOME"

env CODEX_HOME="$CODEX_HOME" "$CODEX_COMMAND" \
  plugin marketplace add "$ROOT" --json >/dev/null
env CODEX_HOME="$CODEX_HOME" "$CODEX_COMMAND" \
  plugin add superpowers@superpowers-dev --json >/dev/null
env CODEX_HOME="$CODEX_HOME" "$CODEX_COMMAND" \
  plugin list --json >"$PLUGIN_LIST"

python3 - "$ROOT" "$CODEX_HOME" "$PLUGIN_LIST" <<'PY'
import filecmp
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
home = Path(sys.argv[2]).resolve()
listing = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
version = json.loads(
    (root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
)["version"]
matches = [
    plugin
    for plugin in listing.get("installed", [])
    if plugin.get("pluginId") == "superpowers@superpowers-dev"
    and plugin.get("enabled") is True
]
if len(matches) != 1:
    raise SystemExit("clean home must enable exactly one superpowers@superpowers-dev")
plugin = matches[0]
if plugin.get("version") != version:
    raise SystemExit(
        f"installed version {plugin.get('version')!r} does not match {version!r}"
    )
source = plugin.get("marketplaceSource", {}).get("source")
if not source or Path(source).resolve() != root:
    raise SystemExit(f"marketplace source {source!r} does not match {str(root)!r}")
cache = home / "plugins/cache/superpowers-dev/superpowers" / version
for relative in (
    ".codex-plugin/plugin.json",
    "skills/selecting-workflow-mode/SKILL.md",
    "skills/selecting-workflow-mode/references/risk-matrix.md",
    "skills/using-superpowers/SKILL.md",
):
    source_file = root / relative
    installed_file = cache / relative
    if not installed_file.is_file():
        raise SystemExit(f"installed cache is missing {relative}")
    if not filecmp.cmp(source_file, installed_file, shallow=False):
        raise SystemExit(f"installed cache differs from checkout: {relative}")
PY

printf 'Clean Codex install verified: %s\n' \
  "$(jq -r '.version' "$ROOT/.codex-plugin/plugin.json")"

if [[ -n "$SESSION_MODEL" ]]; then
  mkdir -p "$PROJECT"
  git -C "$PROJECT" init -q -b main
  git -C "$PROJECT" config user.name "Adaptive Smoke"
  git -C "$PROJECT" config user.email "adaptive-smoke@example.invalid"
  printf 'Adaptive read-only smoke fixture.\n' >"$PROJECT/README.md"
  git -C "$PROJECT" add README.md
  git -C "$PROJECT" commit -q -m fixture

  env CODEX_HOME="$CODEX_HOME" "$CODEX_COMMAND" exec \
    --ephemeral \
    --json \
    -m "$SESSION_MODEL" \
    -C "$PROJECT" \
    'Inspect README.md without modifying anything, then report its purpose.' \
    >"$TRANSCRIPT"

  python3 - "$TRANSCRIPT" <<'PY'
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
count = text.count("Mode: lean")
if count != 1:
    raise SystemExit(f"ephemeral session must declare Mode: lean exactly once; found {count}")
PY
  printf 'Ephemeral Codex session verified: %s\n' "$SESSION_MODEL"
fi
