#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

for test in \
  test-selector-contract.sh \
  test-planning-gates.sh \
  test-execution-gates.sh \
  test-evidence-gates.sh \
  test-docs-and-version.sh
do
  printf '\n== %s ==\n' "$test"
  "$DIR/$test"
done
