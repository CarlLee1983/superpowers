#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_DIR="${WORKFLOW_MODES_TEST_DIR:-$DIR}"

for test in \
  test-selector-contract.sh \
  test-portable-mode-protocol.sh \
  test-planning-gates.sh \
  test-execution-gates.sh \
  test-evidence-gates.sh \
  test-docs-and-version.sh
do
  printf '\n== %s ==\n' "$test"
  "$TEST_DIR/$test"
done

printf '\n== test_state_machine.py ==\n'
python3 -m unittest tests/workflow-modes/test_state_machine.py -v
