# Adaptive Maintenance and Evolution

Maintain the Adaptive Superpowers fork as a reproducible, upstream-derived
distribution. The same maintenance system handles both upstream Superpowers
releases and problems discovered while using the current Adaptive release.

## Context

Adaptive Superpowers preserves the complete upstream workflow in `strict`
mode while allowing risk-proportionate `standard` and `lean` execution. Its
runtime behavior is independent of model names. Model families are evaluation
targets, not routing inputs.

The initial Adaptive implementation was developed on
`feature/adaptive-workflow-modes` and squash-merged into the personal fork.
That development branch no longer contains the release history or later
hotfixes. Future work must therefore start from the personal fork's released
`main`, never from the original feature branch.

## Goals

- Provide one repeatable workflow for upstream synchronization and Adaptive
  evolution.
- Keep every Adaptive release tied to a specific stable upstream version.
- Preserve upstream behavior as the `strict` compatibility baseline.
- Keep Adaptive modifications small, explicit, and organized per skill.
- Require evidence from a real failure or an upstream diff before changing
  behavior-shaping skill prose.
- Test policy invariants without overfitting to one model's natural-language
  phrasing.
- Publish immutable, reproducible releases that Codex and other harnesses can
  install by tag.

## Non-goals

- Automatically merging upstream releases.
- Routing workflow modes from model names or model capability allowlists.
- Maintaining long-term support branches for every upstream version.
- Adding runtime telemetry, learned preferences, or remote policy services.
- Rewriting published tags or releases.
- Treating every harmless wording variation as a new transcript contract.

## Repository Topology

Use conventional remote ownership:

- `origin`: `CarlLee1983/superpowers`, the released Adaptive fork.
- `upstream`: `obra/superpowers`, the upstream project.

Local `main` tracks `origin/main` and represents the current released Adaptive
line. Upstream state is consumed through remote-tracking references and stable
tags; no local release branch tracks upstream `main`.

Use these branch classes:

- `main`: the only Adaptive release line.
- `sync/upstream-vX.Y.Z`: temporary integration branch for an upstream tag.
- `feature/adaptive-<topic>`: an Adaptive behavior or maintenance improvement.
- `fix/adaptive-<topic>`: a bounded regression or packaging fix.

All new branches start from the current Adaptive `main`. Historical feature
branches may be retained as archives, but they are never release bases.

## Upstream Base Identity

The repository records the exact upstream base in root-level
`.adaptive-base.json`:

```json
{
  "repository": "https://github.com/obra/superpowers.git",
  "tag": "v6.1.1",
  "commit": "d884ae04edebef577e82ff7c4e143debd0bbec99"
}
```

The existing version tooling and `.codex-plugin/plugin.json` remain
authoritative for the Adaptive version. CI verifies that:

- the upstream tag exists;
- the manifest's Adaptive version begins with the upstream `X.Y.Z` version;
- all plugin and harness manifests contain the same Adaptive version; and
- the release tag resolves to the tested commit.

The base metadata is authoritative only for upstream identity. Documentation
may explain the relationship but must not become a second source of truth.

## Version Policy

Adaptive versions use:

```text
<upstream-version>-adaptive.<revision>
```

Rules:

- An Adaptive-only improvement increments `<revision>`.
- A packaging, metadata, or release hotfix also increments `<revision>`.
- Synchronizing a new upstream patch, minor, or major version resets the
  Adaptive revision to `1`.
- Only stable upstream tags are normal synchronization bases.
- Every published Adaptive tag is immutable.

Examples:

| Change | Version |
|---|---|
| Adaptive improvement after `6.1.1-adaptive.3` | `6.1.1-adaptive.4` |
| Upstream releases `6.1.2` | `6.1.2-adaptive.1` |
| Upstream releases `6.2.0` | `6.2.0-adaptive.1` |
| Packaging hotfix after `6.2.0-adaptive.1` | `6.2.0-adaptive.2` |

## Maintenance Entry Points

### Upstream release

Start this path when upstream publishes a stable tag that should become the
new Adaptive base. Do not synchronize merely because upstream `main` moved.

### Observed Adaptive problem

Start this path when a real session or reproducible integration check reveals
one of the following:

- incorrect workflow-mode selection;
- unnecessary process or approval overhead;
- a missed strict-risk trigger;
- an explicit override not being respected;
- a process skill ignoring its active-mode policy;
- invalid or insufficient verification behavior;
- a harness loading, packaging, metadata, or hook incompatibility; or
- an upstream-compatible strict workflow regression.

Capture the triggering request, relevant environment, selected mode, observed
events, expected behavior, and installed Adaptive version. Redact secrets and
production data before retaining evidence.

## Common Workflow

Both entry points use the following lifecycle.

### 1. Establish the base

- Fetch upstream and personal-fork tags.
- Start a new branch from the current Adaptive `main`.
- Confirm the recorded upstream base and installed Adaptive version.
- Keep the worktree clean before integration or reproduction.

### 2. Produce change evidence

For an upstream release, review the tagged upstream diff grouped into:

- skill behavior;
- harness and plugin integration;
- hooks and bootstrap behavior;
- tests and evaluation infrastructure; and
- documentation and release metadata.

For an observed problem, reproduce the failure with the smallest realistic
case. A behavior-shaping change requires a failing behavioral or structural
test before editing the skill. A purely mechanical metadata defect may use a
strict parser or package validation failure as its regression case.

### 3. Route changes per skill

Each process skill has one declared mode policy. Upstream synchronization
reviews affected skills independently rather than treating the fork as one
large prose patch.

Apply these conflict rules:

1. Accept upstream skill-body improvements into the `strict` path.
2. Preserve the Adaptive mode selector and risk matrix unless evidence changes
   their contract.
3. Reapply the smallest mode gate needed around the updated upstream behavior.
4. Define an explicit policy before shipping any new upstream process skill.
5. Prefer upstream manifest and harness changes unless an Adaptive regression
   test proves that a compatibility exception is still necessary.
6. Preserve domain and artifact skills in every mode.

Do not resolve a prose conflict by blindly choosing either side. Confirm the
resulting behavior for `lean`, `standard`, `strict`, explicit overrides, and
automatic promotion.

### 4. Validate in layers

Run validation from narrowest to broadest:

1. Syntax and metadata validation for each modified skill or manifest.
2. Focused per-skill mode-policy tests.
3. Shared static workflow contracts.
4. Structured event/state-machine tests.
5. Upstream tests affected by the synchronization.
6. A bounded live matrix on Codex and Claude for behavior changes.
7. A clean install and ephemeral new-session smoke test for release changes.

Failures must retain raw command status. A known platform-dependent baseline
failure may be accepted only when it is reproduced on the unchanged base and
recorded in the pull request.

### 5. Review and release

- Bump all declared manifests with the version tool.
- Audit the repository for stale version strings.
- Open a pull request that identifies the upstream base or observed failure,
  explains every compatibility exception, and lists fresh validation evidence.
- Obtain human review of the complete diff.
- Merge to the personal fork's `main`.
- Create an annotated immutable tag and GitHub release.
- Pin the Codex marketplace to that tag and reinstall the plugin.
- Verify the installed cache, enabled version, release commit, and bootstrap
  behavior in a new ephemeral session.

## Adaptive Policy Architecture

Adaptive behavior remains centralized in the selector and risk matrix. Each
process skill contains only the gate needed to consume the active mode. The
rest of the skill stays as close to upstream as practical.

Maintain `docs/adaptive-skill-policy.md` as the policy inventory. It states,
for every process skill:

- behavior in `lean`;
- behavior in `standard`;
- behavior in `strict`;
- behavior when explicitly requested; and
- required invariant tests.

The inventory is a review and test input, not a second runtime policy engine.
Runtime instructions remain in the skills so every supported harness can
consume them without a new dependency.

## Test Architecture Direction

The initial transcript test harness is intentionally strict, but continuing to
encode every acceptable sentence and punctuation variation will make upstream
synchronization increasingly expensive and model-specific.

Evolve tests toward three layers:

### Static policy contracts

Check that skills expose and preserve their declared mode gates, explicit
request behavior, strict compatibility path, and verification floor.

### Structured state-machine contracts

Test observable event invariants instead of exact prose wherever possible:

- one mode declaration per new task;
- no project mutation before the applicable readiness gate;
- explicit non-strict overrides remain active and receive warnings;
- automatic strict promotion is evidence-backed and pauses before mutation;
- no automatic demotion within a task;
- explicit skill requests remain available; and
- completion claims follow fresh verification evidence.

Exact text remains contractual only where the protocol requires a closed,
machine-detectable line.

### Live model evaluations

Use current GPT and Claude models as evaluation axes. Compare behavior across
models, but never add model names to runtime selection logic. Keep the live
matrix small and representative: lean, standard, strict, override, promotion,
explicit skill request, and one harness-loading smoke test.

## Improvement Metrics

Evaluate Adaptive changes against both efficiency and safety:

- task success and regression rate;
- strict-risk miss rate;
- unnecessary strict-promotion rate;
- workflow-mode classification accuracy;
- missing or invalid verification rate;
- tool calls and conversation turns;
- planning artifacts created; and
- time and token cost.

An improvement must not trade a material safety or correctness regression for
lower process cost. Tune policy from repeated real-session evidence, not a
single model-specific phrasing failure.

## Failure and Rollback

- Never repair an installed plugin cache as the durable fix.
- Reproduce and fix the problem in the repository, then publish a new Adaptive
  revision.
- If a release is unusable, leave its tag intact, mark the GitHub release as
  superseded, and publish the next revision.
- The previous immutable tag remains the rollback target for Codex.
- If an upstream synchronization changes strict behavior unexpectedly, stop
  the release and compare the affected skill directly with the upstream tag.

## Delivery Phases

### Phase 1: Maintenance foundation

- Normalize remotes and local branch tracking.
- Archive the initial development branch as non-release history.
- Add upstream-base metadata.
- Add the per-skill policy inventory.
- Add a concise synchronization and release checklist.
- Remove hard-coded test version values in favor of manifest-derived values.

### Phase 2: Test maintainability

- Identify transcript assertions that represent state invariants.
- Move those assertions into structured state-machine checks.
- Retain exact prose assertions only for closed protocol lines.
- Preserve the existing live scenario coverage while reducing grammar
  overfitting.

### Phase 3: Safe automation

- Detect new stable upstream releases and report them without merging.
- Generate a grouped upstream-change report.
- Automate version consistency, base identity, packaging, and install smoke
  checks.
- Keep conflict resolution, behavior changes, merge approval, and release
  publication human-reviewed.

## Acceptance Criteria

The maintenance system is complete when:

- every released Adaptive version identifies one stable upstream base;
- new work starts from the personal fork's released `main`;
- both maintenance entry points follow the same evidence and release gates;
- every process skill has one reviewable mode policy;
- upstream strict improvements can be integrated without replacing Adaptive
  routing;
- tests enforce state and safety invariants without depending broadly on model
  wording;
- all manifests and release metadata stay synchronized; and
- a previous immutable Adaptive tag can restore the Codex installation.
