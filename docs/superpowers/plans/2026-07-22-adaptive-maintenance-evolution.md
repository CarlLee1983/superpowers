# Adaptive Maintenance and Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible maintenance system for both stable upstream Superpowers updates and problems discovered in an installed Adaptive release.

**Architecture:** Root metadata records the immutable upstream base, while one Python validator derives the Adaptive version from the Codex manifest and checks every declared manifest. Markdown inventories keep per-skill policy and release decisions reviewable; test-only state-machine and reporting tools validate behavioral invariants and group upstream diffs without becoming runtime dependencies. GitHub Actions call the same repository scripts used locally.

**Tech Stack:** Python 3 standard library, Bash 3.2-compatible orchestration, Markdown, JSON, git, GitHub Actions, `jq`, `rg`.

**Spec:** `docs/superpowers/specs/2026-07-22-adaptive-maintenance-evolution-design.md`

## Global Constraints

- Start all work from the personal fork's released `main`; this branch was created from `personal/main` at `9b206439b530f922c7b0e24e8a7601013cb7e087`.
- Preserve upstream behavior as the `strict` compatibility baseline.
- Keep Adaptive runtime routing model-independent.
- Use `6.1.1-adaptive.3` as the current Adaptive version; do not bump it for unreleased maintenance tooling.
- Record upstream identity only in `.adaptive-base.json`; `.codex-plugin/plugin.json` remains the Adaptive version authority.
- Use only Python and shell standard tooling; add no runtime dependency.
- Treat published tags as immutable.
- Keep upstream detection read-only: it may report a new stable tag but must not merge it.
- Execute inline in the current checkout, as previously selected by the human partner; do not dispatch subagents.
- Follow RED-GREEN-REFACTOR for new validators and scripts.

---

## File Map

| Path | Responsibility |
|---|---|
| `.adaptive-base.json` | Exact stable upstream repository, tag, and commit identity |
| `scripts/validate-adaptive-base.py` | Metadata, tag, version-prefix, and manifest-consistency validation |
| `scripts/report-upstream-changes.py` | Read-only grouped diff from recorded base to a selected upstream tag |
| `scripts/smoke-codex-install.sh` | Clean Codex marketplace install, cache verification, and optional ephemeral session smoke |
| `scripts/validate-adaptive-release.sh` | Local/CI layered release validation entry point |
| `docs/adaptive-skill-policy.md` | One row per Adaptive process skill with lean/standard/strict/explicit behavior and invariant tests |
| `docs/adaptive-maintenance.md` | Reproduction, synchronization, release, rollback, and install checklist |
| `tests/adaptive-maintenance/test_validate_adaptive_base.py` | Unit and temporary-git-repository tests for base/version validation |
| `tests/adaptive-maintenance/test_policy_inventory.py` | Inventory coverage and required-column contracts |
| `tests/adaptive-maintenance/test_report_upstream_changes.py` | Grouping, rename, deletion, and stable-base reporting tests |
| `tests/adaptive-maintenance/test_smoke_codex_install.py` | Stubbed Codex CLI install, cache, and optional session-smoke tests |
| `tests/adaptive-maintenance/run-tests.sh` | Maintenance-test suite runner |
| `tests/workflow-modes/assert-state-machine.py` | Structured event-trace invariant validator |
| `tests/workflow-modes/test_state_machine.py` | Accepted and rejected workflow traces |
| `tests/workflow-modes/test-docs-and-version.sh` | Manifest-derived version assertions instead of a hard-coded Adaptive version |
| `tests/workflow-modes/run-static-tests.sh` | Includes structured state-machine tests |
| `.github/workflows/adaptive-validate.yml` | Runs repository validation on Adaptive branches and main |
| `.github/workflows/adaptive-upstream-watch.yml` | Scheduled/manual stable upstream detection and grouped job summary |

---

### Task 1: Normalize repository identity and validate the upstream base

**Files:**
- Create: `.adaptive-base.json`
- Create: `scripts/validate-adaptive-base.py`
- Create: `tests/adaptive-maintenance/test_validate_adaptive_base.py`
- Create: `tests/adaptive-maintenance/run-tests.sh`

**Interfaces:**
- Consumes: `--root PATH`, optional `--release-tag TAG`, `.adaptive-base.json`, `.version-bump.json`, and `.codex-plugin/plugin.json`.
- Produces: exit 0 plus `Adaptive <version> is based on <tag> (<commit>)`; validation failures use exit 1 with one `error:` line per defect.

- [ ] **Step 1: Rename the local remotes and implementation branch**

Run:

```bash
git remote rename origin upstream
git remote rename personal origin
git branch -m feature/adaptive-maintenance-evolution
git branch --set-upstream-to=origin/main
```

Expected: `git remote -v` shows `origin` at `CarlLee1983/superpowers` and
`upstream` at `obra/superpowers`; the feature branch is based on and compares
against `origin/main`.

- [ ] **Step 2: Write failing validator tests**

Create `tests/adaptive-maintenance/test_validate_adaptive_base.py` with
`unittest.TestCase` fixtures that initialize a temporary git repository, add
seven JSON manifests through `.version-bump.json`, create an annotated
`v6.1.1` tag, and invoke:

```python
subprocess.run(
    [sys.executable, str(SCRIPT), "--root", str(root)],
    text=True,
    capture_output=True,
)
```

The suite must define these cases: `test_accepts_matching_base_and_versions`,
`test_rejects_missing_base_metadata`,
`test_rejects_adaptive_version_not_matching_upstream_tag`,
`test_rejects_manifest_version_drift`, `test_rejects_tag_commit_mismatch`, and
`test_release_tag_must_resolve_to_head`.

Run:

```bash
python3 -m unittest tests/adaptive-maintenance/test_validate_adaptive_base.py -v
```

Expected: FAIL because `scripts/validate-adaptive-base.py` does not exist.

- [ ] **Step 3: Add the upstream metadata**

Create `.adaptive-base.json`:

```json
{
  "repository": "https://github.com/obra/superpowers.git",
  "tag": "v6.1.1",
  "commit": "d884ae04edebef577e82ff7c4e143debd0bbec99"
}
```

- [ ] **Step 4: Implement the validator**

Implement `scripts/validate-adaptive-base.py` with the exact interfaces
`load_json(path: Path) -> object`,
`dotted_value(document: object, dotted_path: str) -> object`,
`git_commit(root: Path, revision: str) -> str`,
`validate(root: Path, release_tag: str | None) -> list[str]`, and
`main(argv: list[str] | None = None) -> int`.

`validate()` must enforce:

```python
ADAPTIVE_VERSION = re.compile(r"^(\d+\.\d+\.\d+)-adaptive\.(\d+)$")
UPSTREAM_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
```

It must reject missing/extra base keys, a non-stable tag, a non-full commit,
a missing declared manifest, an unreadable dotted field, any version drift,
an Adaptive prefix different from the base tag, a base tag resolving to a
different commit, and a provided release tag that does not resolve to `HEAD`.
Use `git rev-parse --verify <revision>^{commit}` without network access.

- [ ] **Step 5: Verify GREEN and add the suite runner**

Create executable `tests/adaptive-maintenance/run-tests.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests/adaptive-maintenance -p 'test_*.py' -v
```

Run:

```bash
chmod +x scripts/validate-adaptive-base.py tests/adaptive-maintenance/run-tests.sh
tests/adaptive-maintenance/run-tests.sh
scripts/validate-adaptive-base.py
```

Expected: all validator tests pass and the repository reports
`6.1.1-adaptive.3` based on `v6.1.1`.

- [ ] **Step 6: Commit**

```bash
git add .adaptive-base.json scripts/validate-adaptive-base.py tests/adaptive-maintenance
git commit -m "feat: validate adaptive upstream base"
```

---

### Task 2: Add the per-skill policy inventory and maintenance checklist

**Files:**
- Create: `docs/adaptive-skill-policy.md`
- Create: `docs/adaptive-maintenance.md`
- Create: `tests/adaptive-maintenance/test_policy_inventory.py`

**Interfaces:**
- Consumes: process skills containing `<WORKFLOW-MODE-GATE>` or `<WORKFLOW-MODE-DEPTH>`, plus `selecting-workflow-mode` and `using-superpowers`.
- Produces: one Markdown table row per discovered process skill with non-empty Lean, Standard, Strict, Explicit request, and Invariant tests cells.

- [ ] **Step 1: Write the failing inventory contract**

Create `tests/adaptive-maintenance/test_policy_inventory.py`. Parse rows between
`<!-- POLICY-TABLE START -->` and `<!-- POLICY-TABLE END -->`, and assert:

```python
expected = {
    path.parent.name
    for path in (ROOT / "skills").glob("*/SKILL.md")
    if "<WORKFLOW-MODE-GATE>" in path.read_text()
    or "<WORKFLOW-MODE-DEPTH>" in path.read_text()
}
expected |= {"selecting-workflow-mode", "using-superpowers"}
self.assertEqual(set(rows), expected)
self.assertTrue(all(all(cell.strip() for cell in row[1:]) for row in rows.values()))
```

Also assert that `docs/adaptive-maintenance.md` contains the exact headings
`## Observed problem`, `## Upstream synchronization`, `## Validation`,
`## Release`, and `## Rollback`.

Run:

```bash
python3 -m unittest tests/adaptive-maintenance/test_policy_inventory.py -v
```

Expected: FAIL because both documents are absent.

- [ ] **Step 2: Write the policy inventory**

Create `docs/adaptive-skill-policy.md` with columns:

```markdown
| Skill | Lean | Standard | Strict | Explicit request | Invariant tests |
```

Include one row for every test-discovered process skill. Describe existing
behavior, not aspirational behavior. Reference the focused static test file in
the invariant cell: selector/bootstrap in `test-selector-contract.sh`, planning
skills in `test-planning-gates.sh`, execution/review skills in
`test-execution-gates.sh`, and debugging/verification in
`test-evidence-gates.sh`.

- [ ] **Step 3: Write the operational checklist**

Create `docs/adaptive-maintenance.md` with executable commands for both entry
points. The upstream path must fetch `upstream` and `origin`, create
`sync/upstream-vX.Y.Z` from `origin/main`, run the grouped report, update
`.adaptive-base.json`, route every changed process skill through the policy
inventory, validate, review, tag, reinstall, and smoke test. The observed
problem path must record request/environment/mode/events/expected/version,
redact retained evidence, reproduce before editing, branch from `origin/main`,
and publish the next immutable Adaptive revision.

- [ ] **Step 4: Verify GREEN and commit**

```bash
tests/adaptive-maintenance/run-tests.sh
git add docs/adaptive-skill-policy.md docs/adaptive-maintenance.md tests/adaptive-maintenance/test_policy_inventory.py
git commit -m "docs: define adaptive maintenance policy"
```

Expected: all maintenance tests pass.

---

### Task 3: Add structured workflow-state contracts and derive test versions

**Files:**
- Create: `tests/workflow-modes/assert-state-machine.py`
- Create: `tests/workflow-modes/test_state_machine.py`
- Create: `tests/adaptive-maintenance/test_repository_contracts.py`
- Modify: `tests/workflow-modes/run-static-tests.sh`
- Modify: `tests/workflow-modes/test-docs-and-version.sh`

**Interfaces:**
- Consumes: JSON array of event objects on a file path or stdin.
- Produces: exit 0 for a valid event trace; exit 1 and newline-delimited invariant errors for invalid traces.

- [ ] **Step 1: Write failing trace and repository-contract tests**

Define event dictionaries with `event`, `mode`, `override`, `evidence`,
`fresh`, and `status` fields as applicable. Cover
`test_accepts_lean_verified_completion`,
`test_accepts_evidence_backed_automatic_promotion`,
`test_accepts_explicit_override_warning_without_promotion`,
`test_rejects_duplicate_declaration`,
`test_rejects_mutation_before_declaration`,
`test_rejects_automatic_demotion`, `test_rejects_override_promotion`,
`test_rejects_promotion_without_evidence`, and
`test_rejects_completion_without_fresh_successful_verification`.

In `test_repository_contracts.py`, assert
`tests/workflow-modes/test-docs-and-version.sh` does not match
`TARGET_VERSION="[0-9].*-adaptive` and that `run-static-tests.sh` invokes
`python3 -m unittest tests/workflow-modes/test_state_machine.py -v` exactly once.

Run both files. Expected: FAIL because the validator is absent, the version is
hard-coded, and the runner lacks the new suite.

- [ ] **Step 2: Implement the event validator**

Define `VALID_MODES = {"lean", "standard", "strict"}` and implement the exact
interfaces `validate_trace(events: list[dict[str, object]]) -> list[str]` and
`main(argv: list[str] | None = None) -> int`.

Track declaration count, active mode, override, mutation, and the most recent
verification. Enforce one declaration, declaration/readiness before mutation,
promotion only from automatic lean/standard to strict with evidence, no
automatic demotion, warning rather than promotion for explicit non-strict
overrides, and a fresh successful verification after the final mutation and
before a completion claim.

- [ ] **Step 3: Replace the hard-coded test version and wire the runner**

Replace:

```bash
TARGET_VERSION="6.1.1-adaptive.3"
```

with:

```bash
TARGET_VERSION="$(jq -r '.version' "$ROOT/.codex-plugin/plugin.json")"
```

Add this line after shell contract tests in `run-static-tests.sh`:

```bash
python3 -m unittest tests/workflow-modes/test_state_machine.py -v
```

- [ ] **Step 4: Verify RED/GREEN behavior and commit**

```bash
python3 -m unittest tests/workflow-modes/test_state_machine.py -v
python3 -m unittest tests/adaptive-maintenance/test_repository_contracts.py -v
tests/workflow-modes/run-static-tests.sh
git add tests/workflow-modes tests/adaptive-maintenance/test_repository_contracts.py
git commit -m "test: add adaptive workflow state contracts"
```

Expected: all focused and static workflow tests pass.

---

### Task 4: Generate grouped upstream-change evidence

**Files:**
- Create: `scripts/report-upstream-changes.py`
- Create: `tests/adaptive-maintenance/test_report_upstream_changes.py`

**Interfaces:**
- Consumes: `--root PATH`, optional `--base-ref REF`, and required `--target-ref REF`.
- Produces: deterministic Markdown with base/target commits and six groups: Skill behavior, Harness and plugin integration, Hooks and bootstrap, Tests and evaluations, Documentation and release metadata, Other.

- [ ] **Step 1: Write failing grouped-report tests**

Build a temporary git repository with a tagged base and target commit that
adds a skill, modifies a Codex manifest, deletes a hook, renames a test, edits
README, and adds an unmatched file. Assert each `git diff --name-status -M`
line appears exactly once under the expected heading, base defaults from
`.adaptive-base.json`, and unknown revisions return exit 1.

Run:

```bash
python3 -m unittest tests/adaptive-maintenance/test_report_upstream_changes.py -v
```

Expected: FAIL because the reporting script is absent.

- [ ] **Step 2: Implement the report generator**

Implement:

```python
GROUPS = (
    ("Skill behavior", ("skills/",)),
    ("Harness and plugin integration", (".codex-plugin/", ".claude-plugin/", ".cursor-plugin/", ".kimi-plugin/", ".opencode/", ".pi/", "gemini-extension.json")),
    ("Hooks and bootstrap", ("hooks/",)),
    ("Tests and evaluations", ("tests/", "evals/")),
    ("Documentation and release metadata", ("docs/", "README.md", "RELEASE-NOTES.md", "CHANGELOG.md", "package.json", ".version-bump.json")),
)

```

Implement the exact interfaces
`changed_paths(root: Path, base: str, target: str) -> list[str]`,
`classify(change_line: str) -> str`,
`render_report(root: Path, base: str, target: str) -> str`, and
`main(argv: list[str] | None = None) -> int`.

For renames, classify by the destination path. Sort lines within each group.
Include empty groups as `_No changes._` so reviewers can distinguish reviewed
absence from omitted analysis.

- [ ] **Step 3: Verify GREEN and commit**

```bash
chmod +x scripts/report-upstream-changes.py
tests/adaptive-maintenance/run-tests.sh
scripts/report-upstream-changes.py --target-ref v6.1.1
git add scripts/report-upstream-changes.py tests/adaptive-maintenance/test_report_upstream_changes.py
git commit -m "feat: report grouped upstream changes"
```

Expected: tests pass and the current base-to-base report contains six empty
groups.

---

### Task 5: Add layered release validation and read-only upstream automation

**Files:**
- Create: `scripts/validate-adaptive-release.sh`
- Create: `tests/adaptive-maintenance/test_release_runner.py`
- Create: `scripts/smoke-codex-install.sh`
- Create: `tests/adaptive-maintenance/test_smoke_codex_install.py`
- Create: `.github/workflows/adaptive-validate.yml`
- Create: `.github/workflows/adaptive-upstream-watch.yml`
- Modify: `docs/adaptive-maintenance.md`

**Interfaces:**
- Consumes: optional `--release-tag TAG`; `ADAPTIVE_TEST_ROOT` may redirect test executables only in runner self-tests. The install smoke accepts optional `--session MODEL` and `CODEX_BIN` for a test stub.
- Produces: ordered validation with raw command failures; GitHub upstream watch writes a grouped Markdown report to `$GITHUB_STEP_SUMMARY` and never pushes or merges.

- [ ] **Step 1: Write the failing release-runner contract**

Create stub executables under a temporary `ADAPTIVE_TEST_ROOT`, append each
invocation to `ADAPTIVE_RUNNER_LOG`, and assert this exact order:

```text
validate-adaptive-base.py
run-tests.sh
run-static-tests.sh
test-marketplace-manifest.sh
test-package-codex-plugin.sh
smoke-codex-install.sh
test-session-start.sh
```

Assert `--release-tag v6.1.1-adaptive.3` is passed only to the base validator,
and a failing stub stops later commands while preserving the failing status.

Run:

```bash
python3 -m unittest tests/adaptive-maintenance/test_release_runner.py -v
```

Expected: FAIL because the release runner is absent.

- [ ] **Step 2: Implement the release runner**

Create executable `scripts/validate-adaptive-release.sh` using
`set -euo pipefail`. Resolve repository paths by default and test-fixture paths
from `ADAPTIVE_TEST_ROOT`. Invoke each command as a standalone line in the
tested order. Accept only no arguments or `--release-tag TAG`; reject all
other arguments with exit 2.

- [ ] **Step 3: Write and run a failing Codex install-smoke test**

Create a stub `codex` executable that records arguments, returns a valid
marketplace-add result, materializes the expected cache on `plugin add`, emits
one installed `superpowers@superpowers-dev` entry on `plugin list --json`, and
emits JSONL containing `Mode: lean` on `exec --ephemeral`. Assert the smoke
script uses a fresh `CODEX_HOME`, verifies the manifest-derived version and
three routing files, and runs the optional session only when `--session` is
provided.

Run:

```bash
python3 -m unittest tests/adaptive-maintenance/test_smoke_codex_install.py -v
```

Expected: FAIL because `scripts/smoke-codex-install.sh` is absent.

- [ ] **Step 4: Implement the Codex install smoke**

Create `scripts/smoke-codex-install.sh` with `set -euo pipefail`. Use a new
temporary home, run `codex plugin marketplace add "$ROOT" --json`, run
`codex plugin add superpowers@superpowers-dev --json`, and verify the enabled
plugin version, marketplace source, cache directory, selector, risk matrix,
and bootstrap against the checkout. With `--session MODEL`, initialize a
temporary git fixture and run `codex exec --ephemeral --json -m "$MODEL"`
with a low-risk read-only prompt; reject output lacking exactly one
`Mode: lean` declaration. Always remove the temporary home and fixture.

- [ ] **Step 5: Add validation CI**

Create `.github/workflows/adaptive-validate.yml` for pull requests, pushes to
`main`, and manual dispatch. Use `actions/checkout@v4` with `fetch-depth: 0`,
fetch `https://github.com/obra/superpowers.git` tags into local tag refs, install
`jq` and `rg` only when missing, then run:

```bash
scripts/validate-adaptive-release.sh
```

- [ ] **Step 6: Add the upstream watcher**

Create `.github/workflows/adaptive-upstream-watch.yml` for a weekly schedule
and manual dispatch. Grant only `contents: read`. Checkout with full history,
fetch upstream tags, choose the highest tag matching
`^v[0-9]+\.[0-9]+\.[0-9]+$`, compare it to `.adaptive-base.json`, and when
different run:

```bash
scripts/report-upstream-changes.py --target-ref "$latest" > upstream-report.md
cat upstream-report.md >> "$GITHUB_STEP_SUMMARY"
```

When equal, write `Adaptive already uses <tag>.` to the summary. Do not create
a branch, issue, pull request, tag, or release.

- [ ] **Step 7: Verify workflows and runner**

```bash
chmod +x scripts/validate-adaptive-release.sh
python3 -m unittest tests/adaptive-maintenance/test_release_runner.py -v
python3 -m unittest tests/adaptive-maintenance/test_smoke_codex_install.py -v
tests/adaptive-maintenance/run-tests.sh
scripts/validate-adaptive-release.sh
git diff --check
```

Expected: focused tests, maintenance tests, workflow-mode tests, Codex package
tests, marketplace tests, and hook tests all pass with no diff errors.

- [ ] **Step 8: Update the checklist and commit**

Document `scripts/validate-adaptive-release.sh` as the pre-PR and pre-tag gate,
document `--release-tag` as the tag-to-HEAD check, and require
`scripts/smoke-codex-install.sh --session <current Codex model>` before a
release that changes routing, packaging, or bootstrap behavior.

```bash
git add scripts/validate-adaptive-release.sh scripts/smoke-codex-install.sh tests/adaptive-maintenance/test_release_runner.py tests/adaptive-maintenance/test_smoke_codex_install.py .github/workflows docs/adaptive-maintenance.md
git commit -m "ci: automate adaptive release validation"
```

---

### Task 6: Final requirement verification

**Files:**
- Modify only if verification reveals a documented gap.

**Interfaces:**
- Consumes: design spec, this plan, complete branch diff, and all repository validators.
- Produces: fresh evidence that every acceptance criterion has a committed implementation.

- [ ] **Step 1: Run complete verification**

```bash
scripts/validate-adaptive-base.py
tests/adaptive-maintenance/run-tests.sh
tests/workflow-modes/run-static-tests.sh
scripts/validate-adaptive-release.sh
scripts/report-upstream-changes.py --target-ref v6.1.1
git diff --check origin/main...HEAD
git status --short --branch
```

Expected: every command exits 0; the report has six reviewed empty groups; the
working tree is clean and the feature branch is ahead of `origin/main`.

- [ ] **Step 2: Audit requirements and scope**

Check every Acceptance Criteria item in the design against a concrete file or
test. Confirm the diff contains no model-name routing, no runtime dependency,
no installed-cache edits, and no publication action.

- [ ] **Step 3: Review the complete diff**

```bash
git diff --stat origin/main...HEAD
git log --oneline --decorate origin/main..HEAD
```

Do not push or open a pull request until the human partner has reviewed the
complete proposed diff, as required by `AGENTS.md`.
