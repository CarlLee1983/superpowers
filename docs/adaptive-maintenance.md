# Adaptive maintenance

Use this workflow for both upstream Superpowers releases and problems observed
while running the current Adaptive release. The released `origin/main` is the
only branch base. `feature/adaptive-workflow-modes` is historical development
state and must not be used as a release base.

Repository remotes use:

```text
origin    https://github.com/CarlLee1983/superpowers.git
upstream  https://github.com/obra/superpowers.git
```

## Observed problem

1. Record the triggering request, harness and version, model and version,
   selected mode, observable events, expected behavior, and installed Adaptive
   version. Redact secrets, credentials, customer data, and production data.
2. Confirm the installed version and repository base:

   ```bash
   codex plugin list --json
   scripts/validate-adaptive-base.py
   ```

3. Reproduce the smallest realistic failure before editing. Preserve raw exit
   status and the minimal redacted transcript or parser failure.
4. Start from the released fork:

   ```bash
   git fetch origin --tags
   git switch -c fix/adaptive-issue-topic origin/main
   ```

5. Add a failing behavioral, structural, parser, or packaging regression test.
   Change one skill or compatibility surface at a time. Use
   [adaptive-skill-policy.md](adaptive-skill-policy.md) for mode behavior and
   focused invariants.
6. Run focused RED/GREEN validation, then the layered validation below.

## Upstream synchronization

Synchronize stable tags only. Do not merge a moving upstream `main`.

```bash
UPSTREAM_VERSION=6.1.2
git fetch upstream --tags
git fetch origin --tags
git switch -c "sync/upstream-v${UPSTREAM_VERSION}" origin/main
scripts/report-upstream-changes.py \
  --target-ref "v${UPSTREAM_VERSION}" \
  > "/tmp/upstream-v${UPSTREAM_VERSION}-report.md"
```

Review the report by group. For every changed process skill:

1. Accept upstream body improvements into the `strict` path.
2. Preserve the selector and risk matrix unless evidence changes their
   contract.
3. Reapply the smallest lean/standard gate from
   [adaptive-skill-policy.md](adaptive-skill-policy.md).
4. Define a policy row and focused test before adding a new process skill.
5. Prefer upstream harness and manifest changes unless an Adaptive regression
   proves a compatibility exception is still required.

After integration, update `.adaptive-base.json` to the exact stable upstream
tag and full commit. Set every version manifest to
`<upstream-version>-adaptive.1` with `scripts/bump-version.sh`.

## Validation

Run from narrowest to broadest and keep every failing command's raw status:

```bash
scripts/validate-adaptive-base.py
tests/adaptive-maintenance/run-tests.sh
tests/workflow-modes/run-static-tests.sh
tests/codex/test-marketplace-manifest.sh
tests/codex/test-package-codex-plugin.sh
tests/hooks/test-session-start.sh
```

For behavior changes, run the bounded live cases relevant to the diff on one
current Codex model and one current Claude model. The complete release matrix
contains lean, standard, strict, override, promotion, explicit skill request,
and one clean-install bootstrap smoke. Model names are evaluation axes, never
runtime routing inputs.

A platform-dependent failure may be accepted only when the identical failure
is reproduced on unchanged `origin/main` and recorded in the pull request.

## Release

1. Choose the immutable version:
   - Adaptive-only change or packaging hotfix: increment the Adaptive revision.
   - New upstream stable base: reset to `adaptive.1`.
2. Update and audit all declared manifests:

   ```bash
   VERSION=6.1.1-adaptive.4
   scripts/bump-version.sh "$VERSION"
   scripts/bump-version.sh --audit
   ```

3. Run the complete validation and inspect the complete diff. The pull request
   must identify the upstream base or reproduced problem, explain every
   compatibility exception, and include fresh command and live-evaluation
   evidence.
4. Obtain human review, merge to `origin/main`, and verify the merge commit.
5. Create an annotated immutable tag and release:

   ```bash
   git switch main
   git pull --ff-only origin main
   VERSION="$(jq -r '.version' .codex-plugin/plugin.json)"
   git tag -a "v${VERSION}" -m "Adaptive Superpowers ${VERSION}"
   git push origin "v${VERSION}"
   gh release create "v${VERSION}" --verify-tag --generate-notes
   ```

6. Pin the Codex marketplace to the new tag, reinstall the plugin, verify the
   enabled version and cache, and run an ephemeral new session that declares
   the expected mode and loads the Adaptive bootstrap.

Published tags and releases are never rewritten.

## Rollback

Do not repair the installed plugin cache as a durable fix. Reproduce in the
repository and publish the next Adaptive revision.

If a release is unusable:

1. Leave its tag intact and mark the GitHub release as superseded.
2. Re-pin Codex to the previous immutable Adaptive tag and reinstall.
3. Verify `codex plugin list --json`, the installed cache path, and a new
   ephemeral session.
4. Fix from `origin/main`, publish the next revision, and retain the failed
   release as historical evidence.
