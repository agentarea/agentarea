# Version Management

AgentArea uses a **VERSION-first architecture** for application versioning with **independent chart versioning** for Helm charts.

## Version Architecture

```
VERSION file (0.0.3) - Single source of truth for application version
    ├─> Git tags (v0.0.3)
    ├─> Docker images (0.0.3-abc1234, 0.0.3, 0.0, 0, latest)
    ├─> Python packages (version = "0.0.3" in pyproject.toml)
    ├─> Node packages (version: "0.0.3" in package.json)
    └─> Helm chart appVersion ("0.0.3")

Chart.yaml version (0.0.1) - Independent chart version
    └─> Helm chart packages (0.0.1)
```

## Key Concepts

### Application Version (VERSION file)
- **Location**: `VERSION` file at project root
- **Purpose**: Tracks the version of the application code (API, worker, frontend, etc.)
- **Managed by**: `scripts/bump-version.py` (custom Python script)
- **Synchronized to**: All pyproject.toml files, package.json, Chart.yaml appVersion, .bumpversion.yaml

### Chart Version (Chart.yaml)
- **Location**: `charts/agentarea/Chart.yaml` (`version` field)
- **Purpose**: Tracks the version of the Helm chart configuration
- **Managed by**: Manual edits to Chart.yaml
- **Independent**: Does NOT follow application version

### Why Independent Chart Versioning?

Chart versions should be bumped independently when:
- Chart templates change (new resources, configuration options)
- Chart dependencies update (PostgreSQL, Redis versions)
- Chart values.yaml structure changes
- Chart installation/upgrade logic changes

Chart versions should NOT be bumped when:
- Only application code changes (API, worker, frontend)
- Docker image versions update
- Application version changes

## Docker Image Tags

AgentArea uses a **GitLab-inspired tagging strategy** that combines semantic versioning with commit SHA tracking for full traceability.

### Stable Releases

When a release is published (e.g., `v0.0.3`), Docker images are tagged with:

- `0.0.3-abc1234` - **Immutable**: Specific version + commit SHA (recommended for production)
- `0.0.3` - **Mutable**: Specific patch version
- `0.0-abc1234` - **Rolling with SHA**: Latest patch in 0.0.x series with commit SHA
- `0.0` - **Rolling minor**: Always points to latest patch in 0.0.x series
- `0-abc1234` - **Rolling with SHA**: Latest minor in 0.x.x series with commit SHA
- `0` - **Rolling major**: Always points to latest minor in 0.x.x series
- `latest` - **Latest stable**: Always points to most recent stable release

### Pre-Release Tags (Docker Only)

Pre-release tags are applied at the Docker image level, NOT in the application version:

- Application version stays stable: `0.0.3`
- Docker tags for RC testing: `0.0.3-rc.1`, `0.0.3-rc.2`, `0.0.3-rc.1-abc1234`
- Docker tags for beta: `0.0.3-beta.1`, `0.0.3-beta.1-abc1234`

**Note:** The VERSION file and all package versions always contain stable versions only (e.g., `0.0.3`). Pre-release identifiers are added as Docker image tags for deployment testing purposes.

### Main Branch Builds

Commits to the `main` branch automatically build and tag images as:

- `0.0.3-abc1234` - Current version from VERSION file + commit SHA
- `0.0.3` - Current version from VERSION file (mutable)

Note: `dev`, `commit-*`, and branch-based tags have been removed in favor of version+SHA tags.

### Tag Usage Guidelines

| Use Case | Recommended Tag | Why |
|----------|----------------|-----|
| **Production** | `0.0.3-abc1234` | Immutable, fully traceable, guaranteed not to change |
| **Production (rolling)** | `0.0` | Always get latest patch fixes in 0.0.x |
| **Staging** | `0.0.4-rc.1` | Test release candidates before production |
| **Development** | `0` | Bleeding edge, always latest version |
| **Pinned version** | `0.0.3` | Specific patch, but may be rebuilt |

### Examples

```yaml
# Production deployment (Helm values.yaml)
# Pin to exact version+SHA for immutability
image:
  repository: agentarea/agentarea-api
  tag: "0.0.3-abc1234"

# Production with automatic patch updates
# Get security fixes automatically
image:
  repository: agentarea/agentarea-api
  tag: "0.0"

# Staging/Testing with release candidate
image:
  repository: agentarea/agentarea-api
  tag: "0.0.4-rc.1"

# Development with latest version
image:
  repository: agentarea/agentarea-api
  tag: "0"
```

### Docker Registries

All images are pushed to:
- **Docker Hub**: `agentarea/agentarea-{component}`
- **Private Registry**: Configured via GitHub secrets (for releases and main branch builds)

Components: `api`, `worker`, `frontend`, `bootstrap`, `mcp-manager`

## Release Process

### 1. Prepare Release (Bump Application Version)

Trigger the `Prepare Release` workflow with desired bump type:

```bash
# Via GitHub UI: Actions → Prepare Release → Run workflow
# Select release type: patch, minor, or major
```

**Release Types:**
- **patch**: Bug fixes (0.0.3 → 0.0.4)
- **minor**: New features (0.0.3 → 0.1.0)
- **major**: Breaking changes (0.0.3 → 1.0.0)

**Note:** Application versions are always stable. For release candidate testing, use the same application version with Docker-specific RC tags (e.g., Docker tag `0.0.3-rc.1` with application version `0.0.3`).

This workflow:
1. ✅ Verifies all versions are synchronized
2. ⬆️ Runs `scripts/bump-version.py` with selected type
3. 📝 Updates VERSION file and propagates to all package files
4. 🎯 Syncs Chart.yaml `appVersion` (NOT `version`)
5. ✅ Verifies synchronization after bump
6. 📋 Creates release PR (e.g., `release/v0.0.4`)

**Note:** We use a custom Python script instead of `bumpversion` tool. Configuration is in `.bumpversion.yaml` (modern YAML format).

### 2. Review Release PR

- Review changes in PR
- Verify all version files updated correctly
- **If chart configuration changed**: Manually bump chart version in `charts/agentarea/Chart.yaml`
- Optionally add release notes to CHANGELOG

### 3. Merge Release PR

On merge to main:
1. 🏷️ `release-publish` workflow creates git tag (e.g., `v0.0.4`)
2. 🐳 Builds and pushes Docker images with version tag
3. 📦 Tag push triggers `release-helm-oci` workflow
4. 🚀 Helm chart published to GHCR

### Dev/Test Releases (Helm Chart)

For testing Helm charts without a full release:

```bash
# Via GitHub UI: Actions → Release Helm Chart to GHCR → Run workflow (manual dispatch)
```

This creates a dev version like:
- Chart version: `0.0.1-dev.abc1234`
- App version: `0.0.3-dev.abc1234`

Dev versions can be redeployed (unlike official releases).

## Version Verification

CI automatically verifies version synchronization on every push and PR:

```bash
# Run locally to check:
./scripts/verify-version-sync.sh
```

This verifies:
- ✅ .bumpversion.yaml current_version matches VERSION
- ✅ All pyproject.toml files match VERSION
- ✅ package.json matches VERSION
- ✅ Chart.yaml appVersion matches VERSION
- ℹ️ Chart.yaml version is NOT checked (independent)

## Manual Version Changes

### Bump Application Version Locally

⚠️ **Not recommended** - use the `Prepare Release` workflow instead.

If you must bump locally:

```bash
# 1. Ensure versions are synchronized
./scripts/verify-version-sync.sh

# 2. Bump version (patch/minor/major)
python3 scripts/bump-version.py patch  # or minor, or major

# 3. Verify synchronization
./scripts/verify-version-sync.sh
```

The `bump-version.py` script automatically:
- Updates VERSION file
- Updates all pyproject.toml files
- Updates package.json
- Updates Chart.yaml appVersion
- Updates .bumpversion.cfg

### Bump Chart Version Independently

When chart configuration changes:

```bash
# 1. Edit charts/agentarea/Chart.yaml
# Update the 'version' field (e.g., 0.0.1 -> 0.0.2)

# 2. Commit the change
git add charts/agentarea/Chart.yaml
git commit -m "chore(chart): bump chart version to 0.0.2"
```

Chart version should follow semantic versioning:
- **MAJOR**: Incompatible changes (breaking upgrades)
- **MINOR**: New features (backwards-compatible)
- **PATCH**: Bug fixes, small improvements

## Helper Scripts

### `scripts/bump-version.py`

Bump application version across all files:

```bash
python3 scripts/bump-version.py patch   # 0.0.3 → 0.0.4
python3 scripts/bump-version.py minor   # 0.0.3 → 0.1.0
python3 scripts/bump-version.py major   # 0.0.3 → 1.0.0
```

This script:
- Updates VERSION file with new version
- Propagates to all pyproject.toml files
- Updates package.json
- Updates Chart.yaml appVersion
- Updates .bumpversion.yaml
- Used by the "Prepare Release" workflow

### `scripts/get-version.sh`

Read VERSION file in various formats:

```bash
./scripts/get-version.sh           # Returns: 0.0.3
./scripts/get-version.sh --tag     # Returns: v0.0.3
./scripts/get-version.sh --dev     # Returns: 0.0.3-dev.abc1234
```

### `scripts/verify-version-sync.sh`

Verify all app versions are synchronized:

```bash
./scripts/verify-version-sync.sh
# ✅ All versions synchronized to 0.0.3
```

### `scripts/sync-versions.py`

Emergency synchronization script (syncs to VERSION file):

```bash
python3 scripts/sync-versions.py
# ✅ All versions synchronized to 0.0.3
```

Use this for emergency recovery when versions are out of sync.

### `scripts/update-appversion.py`

Sync Chart.yaml appVersion to VERSION file:

```bash
python3 scripts/update-appversion.py
# ✅ Updated Chart appVersion to 0.0.3 (chart version unchanged)
```

Called automatically by bump-version.py.

## Troubleshooting

### Versions Out of Sync

**Symptom**: CI fails with "version mismatch" error

**Solution**:
```bash
# Check current state
./scripts/verify-version-sync.sh

# Use sync script to fix
python3 scripts/sync-versions.py

# Verify fix
./scripts/verify-version-sync.sh
```

### Git Tag Doesn't Match VERSION

**Symptom**: Tag says v0.0.X but VERSION file says 0.0.Y

**Solution**:
```bash
# Delete wrong tag
git tag -d v0.0.X
git push origin :refs/tags/v0.0.X

# Create correct tag
git tag -a v$(cat VERSION) -m "Release v$(cat VERSION)"
git push origin v$(cat VERSION)
```

### Chart appVersion Not Synchronized

**Symptom**: Chart.yaml appVersion doesn't match VERSION file

**Solution**:
```bash
# Sync appVersion to VERSION file
python3 scripts/update-appversion.py

# Verify
grep appVersion charts/agentarea/Chart.yaml
cat VERSION
```

### Helm Dev Release Shows 0.0.0-dev

**Symptom**: Manual Helm chart release creates `0.0.0-dev.<sha>` instead of expected version

**Cause**: This was the old behavior when workflow read from git tags

**Solution**: This should no longer happen after the workflow update. The workflow now:
- Reads chart version from Chart.yaml
- Reads app version from VERSION file
- Creates `<chart-version>-dev.<sha>` for dev releases

If still happening, ensure you're using the updated `.github/workflows/release-helm-oci.yml`.

## Version History Example

```
Application Versions (from VERSION file):
v0.0.1 → v0.0.2 → v0.0.3 → v0.0.4
(Every app release bumps this)

Chart Versions (from Chart.yaml):
0.0.1 → 0.0.2 → 0.0.3
(Only bumped when chart config changes)

Example timeline:
- v0.0.1 app released with chart 0.0.1
- v0.0.2 app released with chart 0.0.1 (no chart changes)
- v0.0.3 app released with chart 0.0.2 (chart had dependency update)
- v0.0.4 app released with chart 0.0.2 (no chart changes)
```

## Best Practices

1. ✅ **Always use the release workflow** for version bumps (not manual edits)
2. ✅ **Verify synchronization** before and after version changes
3. ✅ **Bump chart version** when chart configuration changes
4. ✅ **Use dev releases** for testing Helm charts
5. ❌ **Don't manually edit version files** (except Chart.yaml version)
6. ❌ **Don't commit unsynchronized versions**
7. ❌ **Don't skip version verification** in release PRs

## Questions?

- How do I bump the application version? → Use "Prepare Release" workflow
- How do I bump the chart version? → Manually edit Chart.yaml
- How do I test Helm chart changes? → Use manual dispatch of "Release Helm Chart to GHCR"
- Why are versions out of sync? → Run `verify-version-sync.sh` to diagnose
- Can I bump versions manually? → Not recommended, use workflows

For more details, see:
- `.bumpversion.cfg` - Application version configuration
- `charts/agentarea/Chart.yaml` - Chart version and metadata
- `.github/workflows/` - Release automation workflows
