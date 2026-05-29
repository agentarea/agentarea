# Playwright Critical Test Plan

Date: 2026-05-26
Branch: `wip/local-sync`

This is the tracked version of the `/autoplan` output for adding Playwright coverage.
The runtime copies live in `.omx/plans/prd-playwright-critical-tests-20260526.md`
and `.omx/plans/test-spec-playwright-critical-tests-20260526.md`.

## Target

Add Playwright tests for AgentArea's critical browser-visible workflows:

- auth and protected app shell
- agent creation/editing/deletion
- task/chat execution with SSE events
- MCP/OpenAPI connection setup
- trigger creation and webhook execution
- network topology
- provider/API-key/secret admin surfaces
- workspace import/export and audit views

## Strategy

Use two test layers.

| Layer | Runs | Purpose |
|---|---|---|
| Contract-mocked browser tests | every PR | Fast UI coverage using Playwright network routing for backend, SSE, and error states |
| Full-stack smoke tests | nightly/release | Minimal real-stack confidence over Ory, API, Temporal, MCP/OpenAPI, and trigger paths |

Reason: broad full-stack E2E would be slow and flaky because the critical flows cross
Ory, FastAPI, Temporal, Redis/pub-sub, MCP manager, and external providers. Most PR
coverage should prove user-visible behavior with deterministic mocks; release coverage
should prove the real integration path still works.

## P0 Coverage

| Domain | Routes / Surface | Required Checks |
|---|---|---|
| Auth | `/auth/*`, `(main)` layout, `AuthGuard` | protected routes redirect when unauthenticated; authenticated app shell loads; session expiry returns to login |
| Agent lifecycle | `/agents`, `/agents/create`, `/agents/[id]` | validation, create with model/tools/skills/events, edit, delete, success/error states |
| Task/chat/SSE | `AgentChat`, `FullChat`, `/tasks`, `/tasks/[id]` | user message, task-created event, LLM chunks, tool calls, approval approve/deny, failure clears loading |
| MCP/OpenAPI | `/mcp-servers`, `/mcp-servers/add`, `/mcp-servers/add-openapi`, `/mcp-servers/[id]` | Docker/command/external forms, auth config, OpenAPI URL/JSON preview, verify/deploy status, no secret leaks |
| Triggers/webhooks | `/triggers`, `/triggers/create`, `/triggers/[id]`, `/webhooks/{id}` | cron/webhook create, invalid JSON rejection, enable/disable/delete, public webhook request handling |

## P1 Coverage

| Domain | Required Checks |
|---|---|
| Network topology | nodes/edges render, filters work, detail drawer links to resource pages, metrics degraded state |
| Provider configs/models | create config, discover/test model success and failure, API keys masked |
| API keys/secrets/audit | one-time key reveal, revoke confirmation, masked secrets, audit filters |
| Workspace import/export | YAML export download, invalid YAML rejected, valid import refreshes resources |
| Projects/skills/files | CRUD and associations, upload/create skill, file list/download/missing file error |
| Dashboard/inbox/budgets/policies | loading/empty/error/data states and filters |

## Implementation Tasks

1. Add `@playwright/test`, `playwright.config.ts`, and npm scripts in `agentarea-webapp`.
2. Add fixtures for auth state, API mocks, stable workspace data, SSE streams, and downloads.
3. Add selectors only where roles/labels/headings are insufficient.
4. Implement P0 mocked specs first:
   - `auth.spec.ts`
   - `agent-lifecycle.spec.ts`
   - `task-chat-sse.spec.ts`
   - `mcp-openapi.spec.ts`
   - `triggers-webhooks.spec.ts`
5. Add full-stack smoke project with seeded user/workspace/model/agent/MCP/trigger fixtures.
6. Add P1 mocked specs.
7. Wire CI:
   - PR: lint + Chromium mocked e2e
   - nightly/release: full-stack smoke and cross-browser P0

## Playwright Config Requirements

- `testDir: "./tests/e2e"`
- `baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000"`
- `webServer` for local Next startup
- `forbidOnly: !!process.env.CI`
- `retries: process.env.CI ? 2 : 0`
- `workers: 1` for full-stack smoke
- `trace: "retain-on-failure"`
- `screenshot: "only-on-failure"`
- `video: "retain-on-failure"`
- auth state under `playwright/.auth/` or Playwright output dir, never committed

## Full-Stack Smoke Path

1. Login with seeded Ory test user.
2. Verify dashboard and app shell.
3. Create or use seeded model instance.
4. Create agent.
5. Start task from chat.
6. Observe terminal success or controlled failure with visible event history.
7. Create OpenAPI connection from embedded JSON spec.
8. Create webhook trigger targeting the agent.
9. POST webhook payload and verify a task appears.

## Failure Modes To Catch

| Failure | Required Test Evidence |
|---|---|
| Auth redirect breaks | protected route lands on `/auth/login` |
| Agent form drops tools | detail page shows submitted tool configs |
| SSE loses chunks | final assistant text includes chunks in order |
| Approval action no-ops | endpoint called and UI marks request resolved |
| MCP secret leaks | secret value absent from DOM after submit |
| Trigger invalid JSON accepted | error visible and API not called |
| API key reappears after refresh | secret shown only immediately after creation |
| Full-stack task pipeline broken | task creates and reaches terminal state |

## Known Risks

- `agentarea-webapp/README.md` still describes NextAuth, while current code uses Ory/Kratos.
- The exact Ory seed path for full-stack smoke was not obvious from inspected files.
- `AgentChat` posts to `/api/agents/${agent.id}/tasks/create`; confirm the route exists before implementing chat e2e.
- Existing frontend tests are standalone `tsx` scripts, not a standard test runner.

## Stop Condition

Implementation is complete when:

- Playwright config and scripts exist.
- P0 mocked specs pass locally.
- Full-stack smoke can run against `make up-dev` with documented seed requirements.
- CI publishes Playwright report/traces/screenshots.
- `playwright/.auth/` and test artifacts are ignored.
- Remaining P1/P2 gaps are tracked.
