# Security, Proxy Cleanup & Typing Improvements

**Date:** 2026-03-10
**Priority:** Security > Proxy > Typing

## Phase 1: Security Fixes

### 1a. Code Scanning Fixes (direct code changes)

**Clear-text logging in auth_service.py (#83)**
- File: `agentarea-platform/libs/mcp/agentarea_mcp/application/auth_service.py`
- Issue: CodeQL flags potential sensitive data in log statements
- Fix: The current logging is actually safe (only logs config IDs, not secrets). Add explicit redaction comments or switch to structured logging with allowlisted fields. No real vulnerability here, but we should satisfy the scanner.

**Stack trace exposure in 5 API endpoints (#43-49)**
- Files: `webhooks.py`, `triggers.py`, `agents_tasks.py`, `agents_a2a.py`
- Pattern: `raise HTTPException(status_code=500, detail=f"Failed to X: {e!s}")` leaks exception messages
- Fix: Replace all `detail=f"...{e!s}"` with generic messages. Log the real error server-side only.
- Affected lines (all `except Exception as e` blocks that include `{e!s}` in detail):
  - `webhooks.py:86` - debug_webhook
  - `triggers.py:446,515,594,641,677,723,769,862,914,960,1012,1070` - all CRUD endpoints
  - `agents_tasks.py:166,377,442,485,525,555,608,664,755,854` - task endpoints
  - `agents_a2a.py` - multiple RPC handlers

**Path injection in provider_configs.py (#41-42)**
- File: `agentarea-platform/apps/api/agentarea_api/api/v1/provider_configs.py:267-295`
- Issue: `provider_key` from URL path used directly in `os.path.exists(f"core/static/icons/providers/{provider_key.lower()}.svg")`
- Fix: Validate `provider_key` against allowlist or sanitize to alphanumeric + hyphens only.

**Missing workflow permissions in CI (#56-76)**
- File: `.github/workflows/ci.yml`
- Fix: Add top-level `permissions: contents: read` and per-job overrides where needed.

### 1b. Dependency Upgrades

**Python (already done via `uv lock --upgrade`):**
- authlib 1.6.9 - alg:none bypass fixed (was in 1.3.1+)
- Many other packages upgraded

**Node.js (pnpm overrides needed - all transitive):**
- `basic-ftp >=5.2.0` (via puppeteer > proxy-agent)
- `glob >=10.5.0` (via tailwindcss > sucrase)
- `minimatch >=9.0.7` (via eslint-config-next > @typescript-eslint)
- `rollup >=4.59.0` (via tsup in packages/elements-react)

Approach: Add `pnpm.overrides` in root package.json to force patched transitive versions.

## Phase 2: Proxy Cleanup

### 2a. Remove NEXT_PUBLIC admin URLs
- Remove `NEXT_PUBLIC_ORY_HYDRA_ADMIN_URL` from client env schema
- Move to server-only `ORY_HYDRA_ADMIN_URL` env var
- Update `src/app/api/hydra/login/route.ts` and `consent/route.ts` to only use server env var

### 2b. Fix Hydra route fallback
- Remove fallback chain that falls through to NEXT_PUBLIC vars
- Require `HYDRA_ADMIN_URL` to be set, fail explicitly if missing

### 2c. Fix uploadSkill proxy bypass
- `src/lib/api-factory.ts:752` — change `/api/v1/skills/upload` to `/api/proxy/v1/skills/upload`

## Phase 3: Typing (future PR)

### 3a. Event handler typing
- Replace `any` params in `messageEventHandlers.ts`, `sseParser.ts`, `messageAccumulator.ts`
- Use discriminated union from existing `types/events.ts`

### 3b. Zod for API response validation
- Add zod schemas for key API response types
- Validate at API boundary in `api-factory.ts` and `browser-api.ts`

### 3c. Cleanup remaining `any`
- Work through 246 instances across 77 files
- Priority: API layer (9 instances), event handlers (5), form utilities
