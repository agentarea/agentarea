# Versioning and Releases

AgentArea uses a **build-once / promote-on-tag** release model:

- **ci.yml** builds immutable per-commit Docker images on every merge to `main`.
- **release-publish.yaml** never rebuilds. On a semver git tag (`vX.Y.Z`), it **retags** an already-built image with the stable release tags and creates the GitHub Release.
- **release-helm.yml** publishes the Helm chart on the same tag push.

A local script, `scripts/release.sh`, validates pre-conditions and pushes the tag.

## Version Architecture

```
VERSION file (0.0.8) — single source of truth for application version
    ├─> Git tags              (v0.0.8)
    ├─> Docker images         (0.0.8-abc1234, 0.0.8, 0.0, 0, latest)
    ├─> Python packages       (pyproject.toml version)
    ├─> Node packages         (package.json version)
    ├─> Go constants          (mcp-manager, event-service main.go)
    └─> Helm appVersion       (charts/agentarea/Chart.yaml appVersion)

Chart.yaml version (0.0.1) — independent chart version
    └─> Helm chart packages   (bumped by release-helm.yml on tag push)
```

### Application Version (VERSION file)

- **Location:** `VERSION` at repo root.
- **Purpose:** Single source of truth for the application's version.
- **Managed by:** `scripts/bump-version.py` via the `Prepare Release` workflow.
- **Propagated to:** all `pyproject.toml`, `package.json`, `Chart.yaml` appVersion, `.bumpversion.yaml`, Go `const version` in `agentarea-mcp-manager` and `agentarea-event-service`.

### Chart Version (Chart.yaml `version`)

- **Location:** `charts/agentarea/Chart.yaml` `version` field.
- **Bumped automatically** by `release-helm.yml` on every `v*` tag push (patch by default; manual dispatch lets you choose patch/minor/major).
- Independent of application version. **Do not edit manually.**

## Docker Image Tags

### What gets pushed when

| Event | Workflow | Tags pushed for each of 7 components |
|---|---|---|
| Merge to `main` | `ci.yml` → `docker-build-push.yml` | `<version>-<sha>` (e.g. `0.0.8-a8eaf7b`) — immutable |
| Git tag push `vX.Y.Z` | `release-publish.yaml` | `<version>`, `<maj.min>`, `<maj>`, `latest` — all pointing to the **same digest** as `<version>-<sha>` (retag, no rebuild) |

### Tag semantics

- `0.0.8-a8eaf7b` — **Immutable per-commit.** Built once by ci.yml. Safe to pin in prod.
- `0.0.8` — **Immutable semver.** Created once by release-publish on tag `v0.0.8`. Points to the same digest as the `<version>-<sha>` of that commit. **Never overwritten.**
- `0.0` — **Rolling minor.** Moves forward to the latest `0.0.x` release.
- `0` — **Rolling major.** Moves forward to the latest `0.x.y` release.
- `latest` — Always points to the most recent release.

### Tag usage guidelines

| Use case | Tag | Why |
|---|---|---|
| Production pin | `0.0.8-a8eaf7b` | Fully traceable, guaranteed not to change |
| Production (auto patch) | `0.0` | Gets patch-level fixes automatically |
| Staging | `0.0.8-<latest-main-sha>` | Test unreleased main builds |
| "Show me the latest" | `latest` | Most recent release |

### Components

Seven Docker images are published:

`api`, `worker`, `frontend`, `bootstrap`, `mcp-manager`, `mcp-runner`, `events`

### Registry

All images go to Docker Hub: `agentarea/agentarea-<component>`.

## Release Process

### 1. Prepare Release (bump VERSION)

Via GitHub UI: **Actions → "Prepare Release" → Run workflow** → select `patch`/`minor`/`major`.

The `release-prepare.yaml` workflow:
1. Runs CI validation (lints, tests, build).
2. Runs `scripts/bump-version.py <type>` — bumps VERSION and propagates to all version files.
3. Creates branch `release/vX.Y.Z` and opens a PR labelled `release`.

**Release types:**
- `patch` — bug fixes (0.0.8 → 0.0.9)
- `minor` — new features, backward compatible (0.0.8 → 0.1.0)
- `major` — breaking changes (0.0.8 → 1.0.0)

### 2. Review and merge the release PR

- Verify all version files updated.
- Add release notes to `CHANGELOG.md` if you keep one.
- Merge. The merge to `main` triggers `ci.yml`, which builds and pushes `0.0.9-<sha>` for all 7 components.

**Merging the PR does not publish the release.** It only bumps versions and builds images.

### 3. Publish the release with `scripts/release.sh`

Once `ci.yml` is green on the release PR merge commit:

```bash
git checkout main
git pull
./scripts/release.sh
```

The script performs these checks before creating the tag:

1. Working tree is clean.
2. On `main` (or confirms override).
3. Local `main` is up-to-date with `origin/main`.
4. `VERSION` contains a valid semver; tag `v<version>` doesn't already exist locally or on origin.
5. `scripts/verify-version-sync.sh` passes (all version files agree).
6. `ci.yml` is green on HEAD (via `gh` CLI).
7. All 7 `agentarea-<component>:<version>-<sha>` images exist on Docker Hub.
8. Shows a summary with commit list since the previous tag.
9. Asks `y/N` confirmation.
10. Creates an annotated tag `v<version>` and pushes it to origin.

**Flags:**

```bash
./scripts/release.sh --dry-run        # run checks only, no tag/push
./scripts/release.sh --skip-ci        # skip ci.yml green check (hotfixes)
./scripts/release.sh --skip-images    # skip Docker Hub existence check
```

### 4. Automated: retag + GitHub Release + Helm chart

The tag push triggers two workflows in parallel:

**`release-publish.yaml`:**
1. Validates tag matches VERSION on the tagged commit.
2. For each of 7 components, waits for `<version>-<sha>` to appear in Docker Hub (retries up to 15 min if `ci.yml` is still running).
3. Uses `docker buildx imagetools create` to add tags `<version>`, `<maj.min>`, `<maj>`, `latest` to the existing image. **No rebuild.** Same digest.
4. Creates a GitHub Release with auto-generated notes from `git log <prev-tag>..HEAD`.

**`release-helm.yml`:**
1. Bumps chart `version` (patch by default).
2. Packages the chart and publishes to the `agentarea/helm-charts` repo.

## TL;DR Release Checklist

```
1. Actions → "Prepare Release" → patch/minor/major → run
2. Review + merge the release PR
3. Wait for ci.yml green
4. Locally:  git pull && ./scripts/release.sh
5. Confirm prompt → tag pushed → GitHub Release + Docker retag + Helm chart publish happen automatically
```

## Key Invariants

- `<version>` (bare semver) is **published exactly once**, via retag. It is never overwritten.
- `<version>-<sha>` is built by `ci.yml` on every merge to main. Immutable per-commit.
- `<version>-<sha>` and `<version>` on the release commit share the **same digest** — they are the exact same image under different tags.
- `VERSION` always contains a stable semver (no `-rc`, `-beta`). Pre-release testing uses `<version>-<sha>` directly.
- Chart `version` is owned by `release-helm.yml`; do not edit it manually.

## Why This Model

**Problem (before):** `ci.yml` pushed both `<version>` and `<version>-<sha>` on every merge to main. The bare `<version>` tag was overwritten on every merge, breaking immutability (prod and staging could both run `0.0.8` but be different images) and making rollback unreliable.

**Fix:** `ci.yml` pushes only `<version>-<sha>`. Promotion to the stable `<version>` tag happens exactly once, via retag, when someone pushes a semver git tag. The image is never rebuilt — semver tag and dev tag are bit-identical.

## Verification

Manual CI check anyone can run:

```bash
./scripts/verify-version-sync.sh
```

Verifies:
- `.bumpversion.yaml` `current_version` matches VERSION
- All `pyproject.toml` files match VERSION
- `package.json` matches VERSION
- `Chart.yaml` appVersion matches VERSION
- Go `const version` matches VERSION (mcp-manager, event-service)
- Chart `version` is **not** checked (intentionally independent)

CI runs this on every push and PR via the `version-check` job in `ci.yml`.

## Troubleshooting

### Versions out of sync

`verify-version-sync.sh` or `ci.yml` fails with a mismatch.

```bash
./scripts/verify-version-sync.sh     # see what's wrong
python3 scripts/sync-versions.py     # force-sync everything to VERSION
./scripts/verify-version-sync.sh     # confirm fixed
```

### `release.sh` says "tag already exists on origin"

Someone (or a prior run) already pushed `v<version>`. If you need to re-release the same version:

```bash
# Delete local + remote tag (destructive!)
git tag -d v0.0.9
git push origin :refs/tags/v0.0.9

# Re-run
./scripts/release.sh
```

Prefer bumping VERSION to a new patch instead of re-using a tag.

### `release.sh` says images are missing in Docker Hub

`ci.yml` hasn't finished building the release commit yet, or some component's build failed.

```bash
# Check ci.yml status
gh run list --workflow=ci.yml --commit $(git rev-parse HEAD)

# If still running: wait. If failed: fix, merge a new commit, re-run release.sh.
# release-publish.yaml also retries up to 15 min, so in practice you can tag anyway.
```

### Helm dev release needs testing before a full release

Use manual dispatch on `release-helm.yml` via the Actions UI. That path is not covered by `release.sh`.

### Hotfix on an older release

```bash
# Branch from the old tag
git checkout -b hotfix/v0.0.8-fix v0.0.8

# Fix the issue, bump VERSION to 0.0.9 (or whatever), commit
python3 scripts/bump-version.py patch
git commit -am "fix: critical bug, bump to 0.0.9"

# Open a PR to a hotfix branch (not main, if main has moved on), merge it
# After ci.yml builds images on the hotfix branch, run:
./scripts/release.sh --skip-ci    # skip if ci.yml rules don't cover hotfix branches
```

## Related Files

- `VERSION` — source of truth
- `scripts/bump-version.py` — bumps VERSION + all consumers
- `scripts/release.sh` — pre-flight + tag push
- `scripts/verify-version-sync.sh` — consistency check
- `scripts/sync-versions.py` — emergency resync
- `scripts/update-appversion.py` — sync Chart.yaml appVersion to VERSION
- `scripts/bump-chart-version.py` — chart version bumper (used by release-helm.yml)
- `.github/workflows/release-prepare.yaml` — opens release PR
- `.github/workflows/ci.yml` → `docker-build-push.yml` — builds `<version>-<sha>` on main
- `.github/workflows/release-publish.yaml` — retags on tag push, creates GitHub Release
- `.github/workflows/release-helm.yml` — publishes Helm chart on tag push
