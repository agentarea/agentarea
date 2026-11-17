# agents: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/agents.md`.

## Done (HTTP: 68/68 routes mounted)

- Agents: `GET /agents`, `GET /agents/`, `POST /agents/`, `GET|PATCH|DELETE /agents/{id}`, `POST /agents/{id}/restore`.
  `GET /agents/tools` (agents.py:385-445, `_mcp_tool_response` :365), `GET /agents/presets`, `POST /agents/{id}/install`.
  `/agents/tools` and `/agents/presets` are mounted ahead of `/{agent_id}` and no longer fall through to "Agent not found".
- Skill collections: all 7 routes.
- Skills: all 18 operations. Upload is multipart; a body that is not multipart answers 422 `body.file`.
  `files/{path:path}` is hand-registered and answers 307, or `{url}` with `redirect=false`.
  Packages are immutable and digest-keyed under `skills/<ws>/packages/<sha256>/`, written through `Deps.Blob`.
  Also: versions and rollback, members and flatten, and the bounded YAML frontmatter parser (no aliases or merge keys; PyYAML 1.1 string resolution).
  Limits are 1000 files, 10 MB per file and 50 MB in total. The GitHub import is tokenless through codeload.
- Clients: list, create, get, patch and delete. Links: add or remove a skill, MCP instance, OpenAPI connection or platform toolset (`{toolset:path}`).
  The platform-toolset catalogue is a static table of 22, checked against `mcp-tools.json`.
  Also `POST /clients/{id}/agent` (the harness agent) and runner keys (issue, list, revoke).
- Task definitions: list, create, get, put, delete, run.
- A2A: discovery card, a2a-info and the index; `a2a/rpc` with edge auth and the 300/min limit; `a2a/well-known`; `a2a/agent-cards`;
  the agent-host `POST /` and card. JSON-RPC covers framing, params, the version check and `GetExtendedAgentCard`.
  `a2a_mapping.py` is ported as `domain/a2a_mapping.go`.
- Workspace export `GET /export` and the MCP tool `workspace_config_export`: YAML compatible with PyYAML `safe_dump`.
  The ports are wired in app: skills (`service/export_skills.go`), MCP instances (connections `api.MCPExports`),
  triggers (streams `api.TriggerExports`), the workspace name (identity `ListWorkspaces`). The import side is not in Go (bundles is not ported).
- A2A task methods over runs (`service/a2a_tasks.go`, port `api.A2ARuns` implemented by `runs/service/a2a.go`):
  `SendMessage`, `SendStreamingMessage` (SSE, `handlers/a2a_stream.go`), `GetTask`, `CancelTask`, `ListTasks`, `SubscribeToTask` and the four push-config methods.
  A message starts a run through the runs `start` path `tasks/sync` uses; the agent key, the run authority (starter or admin, else HTTP 403) and the `execute` permission are as in Python.
  Push configs are kept as Python keeps them: the url in `task.parameters["a2a_push_configs"]`, the token in the secret store under `a2a_push_token:<task>:<config>`. The sender (worker `delivery` group, COVERAGE row 28) is not in Go.
- Audit: `agent.create|update|archive|restore`, `skill.create|update|delete`, task-definition create/update/delete and runner-key issue/revoke.
  All go through `governance/api.AuditWriter`, wired late with `Module.Use(Later{...})`.
- `agents/api`: `Definitions`, `Agents` (`agents_*` toolset), `Skills`, `Clients`, `TaskDefs` and `WorkspaceConfig`, through `Module.*Toolset()` and `Module.WorkspaceConfig()`.
- CLI jobs: `SkillsMoveBodiesToPackages`, `SkillsMoveOwnCopiesToPackages`, `SkillsDeleteMovedOwnCopies`, `SkillsRepinCatalogInstalls` and `SkillsRefreshStubInstalls`.
- `AGENTAREA_A2A_AGENT_URL` is `agents.Config`, loaded in `runServe` and checked as `AppSettings._check_a2a_agent_url` checks it.
- `Models` (models `ModelKinds()`) and `Connections` (connections `Loans()`, adapted in app/agents_ports.go) are wired late with `Module.Use(Later{...})`.
  Create and update lend and withdraw inside the agent row's transaction: a failed loan leaves no agent (as Python's request session rolls back).

## Not done, and why

A port that no other module provides yet is declared in `service/deps*.go` and left nil in app. The routes that need it answer 501:

- governance:
  - The delegate secret binding (admin-only).
- connections:
  - `ToolsMCP`: `/agents/tools?include=mcp`.
  - `ClientConnections`: wired late through `Later.ClientConnections` (connections `Attachable()`).
- catalog: catalog projections in the skill list. Install, update, update-all, rollback to a catalog package and the
  repin and refresh-stub jobs are wired (`CatalogSkills` over `CatalogItems`), and so is a run of an uninstalled catalog
  agent from its definition (`CatalogRun`, runs' `CatalogAgents`).
- streams: `TaskDefTriggers`: task-definition delete, and a put that changes the agent.
- identity:
  - `ClientRunnerKeys`: wired late through `Later.ClientRunnerKeys` (identity `RunnerKeys()`).
- A2A: a message with a `taskId` (a follow-up into an existing task) answers unsupported, and a `contextId` alone always starts a new task:
  Python's `_continue` queues the message into the live task (`queue_follow_up`), which runs does not expose. Inline `configuration.taskPushNotificationConfig` is registered, as in Python.
- Runner presence (`Presence`): runs' `NewRunnerPresence` over the Redis the runner sockets mark; without Redis no runner
  connects, and every client reads offline.
- Agent host: `POST /` and the card are mounted on the main mux, not behind `httpx.ByHost`. On a non-agent host they answer 404/405.
  Other paths on an agent host reach the API routes.
- A2A params are checked by top-level name and type only; SendMessage also checks the message fields Python marks required. The agent-cards check covers name, description and skills.
- Audit records carry no `Changes` diff, because `govapi.AuditRecord` has no field for it.
- `Agent*` domain events (empty payload, no consumer) are not ported.
- Behaviour suite: the task-definition lifecycle skips (`skipUnwired`) while its route answers 501.

## Kept behaviour (Python path:line)

Under the 2026-11-12 rule nothing below is kept for FastAPI parity alone. Each item is a protocol, a contract a client reads, or a cheap choice.

- A2A protocol, not FastAPI:
  - SDK error shapes (`jsonrpc_dispatcher.py`, `response_helpers.py`) and the version rule (`version_validator.py`).
  - The anonymous card read (`agents_well_known.py:get_public_agent`).
  - The decision order (`access.py:44-79`).
- The client contract in the shared OpenAPI spec (`api/openapi`) and the webapp's generated client:
  - Create answers 200.
  - `GET /agents` and `/agents/` both exist.
  - The `tools` shape: a `[]`/null column is null, and a legacy dict is `[]`.
  Unifying these (201, one path, always `[]`) means a spec change and a regenerated webapp client. Both are outside this module's write scope; they are candidates for the spec owner.
- Authz before validation on client routes (`api/v1/clients.py`): a refusal never reveals whether the body was valid. This is a security choice.
- A link id that does not parse answers "{label} not found". It names nothing, and the `clients_add_*` tools report the same.
- Skills:
  - A read never moves a pre-package body (`skill_packages.py:128`).
  - File URLs are presigned without a HEAD (`skill_storage_service.py:325`).
- Export skips a trigger the bundle cannot carry, with a warning (`workspace_export_service.py`).
- Error texts are Go's own, with no attempt at byte parity: yaml.v3, one-line validation messages, and network errors.

## Fixed Python bugs (each has a test)

- `libs/agents/agentarea_agents/application/agent_service.py:680` `_resolve_unique_slug`:
  - Before: the slug scan read and the insert were separate, so a concurrent create took the slug and the request failed with a 500.
  - Now: the scan runs in the insert's transaction, and a unique violation on `*_workspace_slug` retries (3 attempts).
  - The same fix applies to collection create.
  - Tests: `TestSlugTakenOnlyForSlugConstraints`, `TestRetryWhenRerunsOnlyALostSlug`.
- `libs/agents/agentarea_agents/application/agent_service.py:253` `harness_agent`:
  - Before: two concurrent first uses created two harness agents. The created agent was not audited.
  - Now: the check and the create run under an advisory lock in one transaction and write `agent.create`.
  - Tests: `TestHarnessAgentMadeOnceUnderConcurrentFirstUse` (red without the lock), and the audit check in `TestClientsLifecycle`.
- `collection_service.py:update`:
  - Before: `PUT` with `"description": null` could not clear the description.
  - Now: null clears it and an absent field keeps it.
  - Test: `TestCollectionUpdateTellsAbsentFromNull`.
- Collection and skill-link writes were separate commits. Go writes them in one transaction.
- `apps/api/agentarea_api/api/v1/agents.py:372`:
  - Before: one stored MCP tool that `ToolResponse` refuses made `GET /agents/tools` a 500.
  - Now: it is skipped with a warning.
  - Test: `TestToolsSkipsAMalformedMCPTool`.
- `apps/api/agentarea_api/tools/agents_toolset.py:104`:
  - Before: `agents_list` advertised `limit`/`offset` and ignored them.
  - Now: `api.Agents.List` pages.
  - Test: `TestPage`.
- `libs/common/agentarea_common/reasoning_effort.py:51`:
  - Before: `reasoning_max_tokens` was checked only when `reasoning_effort` was set.
  - Now: it is always checked, so -1 answers 400.
- `libs/mcp/agentarea_mcp/infrastructure/client_repository.py:84`:
  - Before: the client list had no `ORDER BY`.
  - Now: it is ordered `created_at DESC, id`.
- `api/v1/clients.py:68,77`:
  - Before: a `namespace_prefix` over 64 characters failed in the DB.
  - Now: it answers 422 `string_too_long`.
- `libs/tasks/agentarea_tasks/schemas/dto.py:151` with `task_definition_service.py:81`:
  - Before: task-definition `PUT` silently ignored fields sent as `null`.
  - Now: it answers 422 "may be omitted, but not set to null".
- `skill_service.py:1546`:
  - Before: `_topological_sort` broke ties in hash order.
  - Now: flatten keeps member order.
  - Tests: `TestSkillTopoSortIsDeterministic`, `TestSkillMembersFlattenInMemberOrder`.
- `audit/decorator.py:155-165`:
  - Before: `skill.update`/`skill.delete` were audited on the 404 path.
  - Now: only what happened is audited.
  - Test: `TestSkillAuditOnlyForWhatHappened`.
- `api/v1/skills.py:377`:
  - Before: upload read the file unbounded.
  - Now: it stops at 50 MB + 1 and answers 400.
  - Test: `TestSkillRouteValidation`.
- `api/v1/skills.py:341,383`:
  - Before: the owner grant ran after the create commit.
  - Now: the row, package, version, audit and grant are written together.
  - Test: `TestSkillsLifecycle`.
- `a2a_agent_cards.py:52`:
  - Before: a card that is not a JSON object, a non-UTF-8 body or an invalid URL was a 500.
  - Now: each is a 400. The webapp's `DelegationConfig` shows the detail.
- `jsonrpc_dispatcher.py:handle_requests`:
  - Before: a non-UTF-8 RPC body was `-32603`.
  - Now: it is `-32700` "The request body is not UTF-8".

None of these changes something a client relies on. The checks covered `agentarea-webapp/src`, `agentarea-cli/src` and `api/contract/mcp-tools.json`.

## Run skills (`api.RunSkills`, `service/run_skills.go`)

Python: `activities/agent/config.py` `_resolve_task_resources` (skills), `_runnable_skills`;
`skill_service.py` `run_refusals`, `get_with_catalog(to_run=True)`; `skill_packages.py`
`read_skill_md`/`read_files` with `at`, `_package_of`; `activities/agent/files.py` `activate_skill_activity`.

- `Offered(ws, agentID, selected)`: the agent's skills, then each selected id (deduped, skipped when
  the agent has it): unknown or malformed is `ErrSkillNotFound`, a policy refusal or a name the run
  already has is `ErrSkillRefused`. Then `run_refusals` over all: refused ones are withheld with the reason.
  `Package` is the row's `s3_path` at resolve time.
- `Allow`, `ReadSkillMD`, `PackageFiles` read the row again; the package is `skill.Package` when it lies in
  `skills/catalog/`, `skills/platform/` or `skills/<ws>/` (no `..`, no `\`), else the skill's own; a row
  still holding its body is read from the row. Gone is `ErrSkillNotFound`; an unreadable package (no
  SKILL.md, bad pointer, missing object, unwired catalog or policy) is `ErrSkillRefused`; storage
  failures are `*SkillUnreachableError`.
- A skill installed from the catalog is asked about through catalog `Installs.SkillProvenance`
  (`provenance_for`) and the governance install policy; with either unwired it is a final refusal that
  names the missing port, never silently offered.
- Fixed in Go: `SkillToolset.runnable` let every catalog install through without asking its source;
  it now uses the same `refusals` as a run.
- Not ported: the catalog projection of a selected skill id with no tenant row, the in-process
  immutable-package cache.

### Wiring needed (app, not done here)

- `app/modules.go` agents deps already pass `Blob: artifacts`; the worker needs the same.
- `runsDeps`: `Definitions: newRunDefinitions(runTools{...}, runSkillsPort{s: m.agents.RunSkills()}, runInstructionsPort{p: m.projects.RunInstructions()}, runInputsPort{i: m.sandbox.RunInputs()})`
  and `Skills: skillPackages{s: m.agents.RunSkills()}`.
- Adapters (app/runs_ports.go):

```go
func runsWorkspace(p runsservice.Principal) (scope.Workspace, error) { return scope.NewWorkspace(p.WorkspaceID, "") }

func runsSkillErr(err error) error {
	var u *agentsapi.SkillUnreachableError
	switch {
	case errors.Is(err, agentsapi.ErrSkillNotFound), errors.Is(err, agentsapi.ErrNotFound):
		return errors.Join(runsservice.ErrNotFound, err)
	case errors.Is(err, agentsapi.ErrSkillRefused):
		return errors.Join(runsservice.ErrRefused, err)
	case errors.As(err, &u):
		return &runsservice.UnreachableError{Service: u.Service, Err: u.Err}
	}
	return err
}

type runSkillsPort struct{ s agentsapi.RunSkills }

func (r runSkillsPort) Skills(ctx context.Context, p runsservice.Principal, agent runsapi.AgentSpec, ids []string) ([]runsapi.Skill, []runsapi.WithheldSkill, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, nil, err
	}
	s, w, err := r.s.Offered(ctx, ws, agent.ID, ids)
	return s, w, runsSkillErr(err)
}

type skillPackages struct{ s agentsapi.RunSkills }

func (k skillPackages) Allow(ctx context.Context, p runsservice.Principal, sk runsapi.Skill) error {
	ws, err := runsWorkspace(p)
	if err != nil {
		return err
	}
	return runsSkillErr(k.s.Allow(ctx, ws, sk))
}

func (k skillPackages) ReadSkillMD(ctx context.Context, p runsservice.Principal, sk runsapi.Skill) (string, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return "", err
	}
	body, err := k.s.ReadSkillMD(ctx, ws, sk)
	return body, runsSkillErr(err)
}

func (k skillPackages) Files(ctx context.Context, p runsservice.Principal, sk runsapi.Skill) ([]runsservice.SkillFile, error) {
	ws, err := runsWorkspace(p)
	if err != nil {
		return nil, err
	}
	files, err := k.s.PackageFiles(ctx, ws, sk)
	if err != nil {
		return nil, runsSkillErr(err)
	}
	out := make([]runsservice.SkillFile, len(files))
	for i, f := range files {
		out[i] = runsservice.SkillFile(f)
	}
	return out, nil
}
```

## Reads and writes for other modules (2026-11-15)

- `Inventory()` (`api.Inventory`): the access explorer's lists (agents newest first,
  archived and harness agents left out unless asked, skills, collections, skill counts).
- `CatalogUses()` (`api.CatalogUses`): a catalog sync's moves of skill forks and
  agents' `registry_item_id`, which items they reference, and dropping the platform
  workspace's legacy skill rows (row delete cascades; tuples revoked after, a failure logged).

## Editor blockers and catalog installs (COVERAGE #6, #7; 2026-11-15)

- Approvals: governance `AgentApprovals()` through `Later.Approvals`. Sync runs in the agent write's
  transaction (`db.Session` in the port); release of rules the toggle did not write is admin-only and
  otherwise `*govapi.ApprovalEnforcedError`, 409 `approval_enforced_by_policy` with `targets`.
- Triggers in `POST /agents/`: `Deps.Triggers` (streams `AgentTriggers()` via app `lateAgentTriggers`).
  Specs are checked before the agent exists; a failed create removes the agent (`unmake`).
- `/agents/tools?include=code`: `service.CodeCatalogue`, files and shell plus the platform toolsets
  that have a plane. Deviation: Python also listed web, media, math, context and workspaces, which a
  Go run cannot execute; `app/codetools_test.go` holds the catalogue to `connections.CodeToolsets()`.
- Catalog items: catalog `Installs()` (`catalogapi.Installs`) through `Later.Catalog`; install policy:
  governance `InstallPolicy()` through `Later.InstallPolicy`. `*govapi.InstallRefusedError` is 403.
- Skill install (`service/skill_install.go`, `_fork_catalog_skill` and `store_catalog_item`): the
  policy, then the package (mirrored `spec.package` inside the registry's area; GitHub `source` read
  through catalog `Folder` at its pin, tree checked; inline `content`; legacy `s3_path`; anything else
  is a 400), stored by digest in `catalog_area`; the row, the install mark and the `install` version in
  one transaction. Not ported: the process caches of GitHub heads and tree aliases (a re-install
  fetches again).
- Run provenance of an installed skill: `Installs.SkillProvenance` (a retired registry's item counts).
- Agent presets and install (`service/catalog_agents.go`): presets validate tools as ToolConfig and
  resolve skill keys (`unavailable_skills`); a malformed preset is a 500 naming it. Triggers are
  passed through as objects: the create form posts them back and `POST /agents/` checks them.
  Install resolves id, tenant slug or catalog slug; reuses the workspace's fork (restoring an archived
  one); the fork binds MCP names without refusing unbound ones, requires usable connections, lifts
  approval toggles, starts with no model, and writes the agent, loans, install mark and approval rules
  in one transaction.

### Fixed Python bugs (2026-11-15)

- `apps/api/agentarea_api/api/v1/agents.py:317` (create with a trigger that fails): `delete_agent`
  removed the row but left its connection loans, approval rules and graph tuples. `unmake` removes all
  of them. Test: `TestCreateWithTriggersRollsBackWhenOneFails`.
- `libs/agents/agentarea_agents/infrastructure/catalog_agent_repository.py:49,67,86`: the catalog agent
  reads did not filter `registry_active`, so a retired registry's agent was still a preset and still
  installed. Go reads active registries only. Test: `catalog/store` `TestInstallsReadActiveVisibleItemsOnly`.
- `apps/api/agentarea_api/api/v1/agents.py` `install_agent` (`_resolve_agent_id`, `install_catalog_agent`): install
  by an existing agent's id or slug made no graph check, so any member or an agent subject could restore a private
  archived agent and read it back. Go requires `read` on the agent, and `delete` when it is archived.
  Tests: `TestInstallByAnAgentsIDOrSlugChecksTheGraph`, suite `TestInstallOfAnArchivedAgentNeedsItsDelete`.

### Fixed Go bugs (2026-11-15 review)

- A2A: a personal API key reached `a2aCaller` with its `api_key` credential, so runs `Start` took it for the agent's
  key and skipped `can_invoke`. As in Python's `_user_context`, only an agent key is a credential there; runs also
  skips the check only for a key bound to the agent. Tests: `TestA2ACallerOfAPersonalKeyIsNoAgentKey`,
  runs `TestA2AStartAsksExecuteOfAnyKeyButTheAgentsOwn`, suite `TestA2APersonalKeyNeedsInvokeOnTheAgent`.
- `Approvals.Release` ran in its own transaction before the PATCH was validated; it now runs in the update's
  transaction. Test: `TestUpdateReleasesApprovalsOnlyAfterValidation`.
- The trigger rollback of a failed create ran on the request context (agents `unmake`, streams `AgentTriggers.Create`);
  it now runs on `context.WithoutCancel`. Tests: `TestCreateRollsBackTriggersAfterTheClientLeft`, streams
  `TestCreateRollsBackAfterTheClientLeft`.
- A mirrored catalog `s3_path` with `..` or `\` is refused. The A2A RPC body is read through `http.MaxBytesReader`
  at the edge limit (`serve.Routes.MaxBody`). A page token past int32 is invalid, and runs refuses such an offset.
