# connections: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/connections.md`.

## Runtime port

The mcp-manager is merged into this module (`runtime/`, `gateway/`, owned by
the runtime porter). The rest of connections never calls it over HTTP; it
calls `service.Runtime` (`service/deps.go`), which the runtime side implements
and `app/serve.go` passes as `connections.Deps.Runtime`:

| Method | Was | Shape |
|---|---|---|
| `Gateway() http.Handler` | `ANY {M}/mcp/{id}/mcp` | serves the request path `/mcp/{id}/mcp`; same 503 `X-AgentArea-MCP-Starting` / `Retry-After` and `X-AgentArea-MCP-Start-Failure` conventions; in-process callers send no `X-AgentArea-Manager-Authorization`, so the handler given here must not require it. Signed `X-AgentArea-Context` passes through untouched |
| `Retire(ctx, id) error` | `DELETE {M}/mcp/{id}` (5 attempts, 409/502/503/504 retried) | nil when retired or nothing ran; `*service.RuntimeRetirementError{Conflict}` (409 when a request still holds it, else 503) leaves the desired state unchanged |
| `Health(ctx, id) (RuntimeHealth, error)` | `GET {M}/instances/{id}/health` | `{Healthy, Status}` for the 200 and 503 reports; `service.ErrRuntimeNotRunning` for 404; any other error is reported as `error` |
| `Validate(ctx, name, jsonSpec) (RuntimeValidation, error)` | `POST {M}/containers/validate` dry run | `{Valid, Details (body), Message}`; an error is "unreachable" (503) |
| `ImportPackage(ctx, id) (ImportedPackage, error)` | `POST {M}/packages/import` | `{Image, Command, Port, Package}`; `*service.PackageRejectedError` is final (422), any other error is retried after an hour |

Context signing: the per-instance key stays
`HMAC-SHA256(AGENTAREA_MCP_GATEWAY_SECRET, "agentarea/mcp-context/v1:" + id)`
on both sides.

Runtime side: `runtime.New(runtime.Deps)` returns `*runtime.Runtime`, which
satisfies `service.Runtime` (asserted in `runtime/runtime.go`). `app/mcp.go`
builds it with `newMCPRuntime(ctx, loadMCPConfig(l), mcpDeps{...})`; serve and
worker call the same two functions to get an in-process runtime for
`connections.Deps.Runtime`. `Gateway()` is the in-process handler (no
manager authorization); `ServedGateway()` is the one the mcp role listens with.
`Retire` returns an error that is both the gateway's cause (`errors.Is`
`gateway.ErrInstanceBusy` / `ErrStartInProgress`) and, through `errors.As`, a
`*service.RuntimeRetirementError`. `Validate` is the docker dry run (an error
on kubernetes / data plane, which never had one: the manager answered it only
on docker). `ImportPackage` is `runtime/packages`.

## Runtime/gateway merge

The mcp-manager's MCP half lives here; its sandbox half goes to the sandbox
module. Layout:

| Package | From the manager | What it is |
|---|---|---|
| `gateway/` | `internal/mcpgateway` (handler, telemetry, observer) | the data path: auth, 32 MiB body, cold start, leases, URL upstream, retire; defines `gateway.Runtime` |
| `gateway/storage/` | `internal/mcpstorage` | `/mcp/{id}/storage/...` app storage on the artifacts bucket; issuer of `MCP_MANAGER_URL` / `MCP_STORAGE_TOKEN` |
| `runtime/` | `internal/mcpgateway` (runtime, repository, reaper), `internal/providers`, `internal/secrets` | lifecycle: load, spec build, start under the instance lock, leases, reaper, retirement, events |
| `runtime/store/` | the repository's SQL | sqlc over `mcp_runtime_instances`, `mcp_runtime_request_leases` (owned here) |
| `runtime/workload/` | `internal/backends` interface, `internal/isolation`, image refs | the backend contract |
| `runtime/docker`, `runtime/kube` | `internal/container`, `internal/backends` | the two local backends |
| `runtime/dataplane/` | `internal/dataplane` | the remote backend (client) and the host the `mcp` role runs with `AGENTAREA_MCP_MODE=dataplane` |
| `runtime/packages/` | `internal/packageimage` | npx/uvx package to image |

Role: `agentarea mcp` (`app/mcp.go`) serves the gateway and storage on
HOST/PORT, runs the reaper and the overlay's `Run`; `all` includes it. It opens
the database, secrets and S3 only (no Redis, OpenFGA or authn: the manager had
none). With `AGENTAREA_MCP_MODE=dataplane` it is a remote workload host with no
database.

Dropped, and why:
- The manager's control-plane HTTP API (`/instances`, `/containers/validate`,
  `/packages/import`, `/instances/{id}/health`, list/update/stop/start): the only
  caller was Python's `mcp_manager_client`, replaced by the in-process
  `service.Runtime`. `packages/import`'s own auth went with it.
- Redis event subscription (`MCPServerInstanceCreated/Updated/Deleted` from
  Python): creation is lazy (first request starts the workload), deletion
  calls `Retire`, update needs nothing (the next start reads the row).
- The manager's direct Redis Streams publisher
  (`agentarea.mcp.v1.MCPServerInstanceStatusChanged` / `...Error`, written to
  `domain.events.*` outside any transaction) and Python's
  `MCPServerInstance*` status events: one outbox event,
  `MCPServerInstanceStatusChanged`, data `{instance_id, workspace_id,
  generation, state, transition, reason, error?}`, written in every lifecycle
  transaction (`events.Publish`, created by `system:mcp-runtime`). Nothing
  consumed either shape, so there is no compat layer.
- The in-memory instance cache and the `mcp_server_instances` status writes:
  liveness is `mcp_runtime_instances.state`.
- The JOIN onto `mcp_servers` (catalog-owned): the server spec comes from
  `catalogapi.MCPSpecs.Get`.
- Data-plane list/update/health routes: the client never called them.
- `internal/features` (`AGENTAREA_MCP_FEATURE_*`): every flag but the warm
  pool was read nowhere, and the warm pool is the sandbox's.
- `internal/egress` (the manager's private-address policy for url
  instances): netguard `Member` applies the same `AGENTAREA_HTTP_*` policy.
- `internal/publishedsecrets` is kept for the one MCP key: `LoadConfig` refuses
  an `AGENTAREA_MCP_GATEWAY_SECRET` the repository once shipped.
- `AGENTAREA_ENV` as the backend alias (it means the deployment environment
  in Go) and the container-level `AGENTAREA_STARTUP_TIMEOUT` (the gateway's
  `AGENTAREA_MCP_STARTUP_TIMEOUT` bounds every start).

Environment (existing names only):
- Required: `AGENTAREA_MCP_GATEWAY_SECRET` (>= 32 bytes),
  `AGENTAREA_MCP_LEASE_TTL`, `AGENTAREA_MCP_STARTUP_TIMEOUT`,
  `AGENTAREA_MCP_IDLE_TIMEOUT` (`0` disables the reaper),
  `AGENTAREA_MCP_SWEEP_INTERVAL`.
- Optional: `AGENTAREA_MCP_BACKEND` (docker, kubernetes, dataplane; unset
  detects kubernetes from the service account, else docker),
  `AGENTAREA_MCP_BASE_IMAGE`, `AGENTAREA_MCP_MODE`, `AGENTAREA_MCP_MANAGER_URL`
  (storage on when set), `AGENTAREA_S3_CONDITIONAL_WRITES`, the `AGENTAREA_S3_*`
  blob variables.
- Backends: docker `AGENTAREA_MCP_RUNTIME`, `_NETWORK`, `_NAME_PREFIX`,
  `_MAX_CONTAINERS`, `_MEMORY`, `_CPU`, `_ISOLATION`, `_MAX_MEMORY`,
  `_MAX_CPU`, `AGENTAREA_LOG_WORKLOAD`; kubernetes `KUBECONFIG`,
  `AGENTAREA_K8S_*`, `AGENTAREA_MCP_ISOLATION`; data plane
  `AGENTAREA_MCP_DATAPLANE_URL`, `_TOKEN`, `_INSECURE`, `_ID`, `_ADDR`;
  packages `AGENTAREA_MCP_PACKAGE_REPO`, `AGENTAREA_MCP_IMPORT_TIMEOUT`,
  `AGENTAREA_MCP_NPM_REGISTRY`, `AGENTAREA_MCP_PYPI_URL`.

Enterprise overlay (`ext.WorkloadHooks`, mirrored types in `ext/types.go`):
`MCPWorkload` (was the InstanceSpec hook: egress proxy env and the
`agentarea.io/egress` label), `MCPLifecycle` (runs in the transition's
transaction), `MCPRequests` and `MCPOperations` (metering observers),
`HostRoutes` and `Run`/`Close` as before. Enterprise registers one
`ext.WithWorkloadHooks` factory filling these; `app/mcp.go` adapts them.

Deviations: docker `InternalURL` is the container IP (no host port mapping);
the cold-start reason header is ASCII-sanitized; docker dry-run validation
still pulls an absent image (manager parity). Outbound: workloads and the data
plane through netguard `Internal`, url instances through `Member`.

Gaps: `make tableowner` reads `internal/modules/*/store/queries` only, so
`runtime/store/queries` is not checked. archgen's kubernetes rule now admits
`connections/runtime/kube` as a second workload backend.

## Fixed Python bugs

- Instances: PATCH/DELETE of a platform-managed or another workspace's
  instance wrote secrets / retired its runtime before the 404; now 404 first
  (`TestUpdateRefusesCostOfPlatformConnection`).
- Instances: env-var and context secrets were set in their own transactions
  before the row; now in the row's transaction, so a refused or failed write
  leaves no orphan secret (no test: the secret fakes are not transactional).

- OAuth: auth_service.py:275/:390 (`_get_oauth2_token`/`_refresh_oauth2_token`)
  let concurrent requests with an expired token each spend the same refresh
  token; a rotating provider rejected all but the first and the auth config
  fell into reauth. Refreshes are now serialized per auth config
  (`pg_advisory_xact_lock` on `mcp_auth_refresh:<id>`), and a holder that finds
  a token renewed by another skips the refresh (`TestRefreshRotationIsSerialized`).
- OAuth: auth_service.py:448 stored refreshed credentials without recording
  `secret_key` on a config that had none (platform-managed client_credentials),
  so every call ran the grant again; the key is now set (`TestClientCredentialsTokenIsKept`).
- OAuth AS: mcp_oauth_as.py:375 read a JSON `"scope": null` as the scope "None"
  and refused the registration; null now means the default scopes
  (`TestRegistrationShaping`).

- OpenAPI: libs/openapi/agentarea_openapi/application/service.py:556
  (update_connection) stored the query secrets, then deleted and rewrote the
  header secrets, and only after that checked auth_config_id, base_url and
  spec_url, so a 400 left the secrets half-changed. Every check now runs
  before the first write, and the writes share one transaction
  (`TestUpdateConnectionRefusalWritesNothing`, `TestUpdateConnectionAuthRefusalKeepsHeaders`).
- OpenAPI: service.py:201 (create_connection) stored the header, query and
  URL-variable secrets before it fetched and parsed the spec. A later failure
  left orphan secrets. Now the fetch and parse come first, and the secrets are
  written in the row's transaction. A failed write removes any secret a
  non-transactional backend kept (`TestCreateConnectionFailureLeavesNoSecrets`).
- OpenAPI: service.py:556 saved a PATCHed `spec_content` without
  re-deriving `available_tools`, which kept the old tools. Now the tools are
  re-derived, and a spec that does not parse is a 400 (`TestUpdateConnectionSpecRederivesTools`).
- OpenAPI: PATCH `{"name": null}` / `{"base_url": null}` hit the NOT NULL
  columns and answered 500. Now they answer 422. service.py:597 skipped the
  address check for an empty `base_url`; now it is checked (`TestPatchOpenAPIConnection`).

- MCP calls: execute_tool added the auth config's headers only when the
  instance had no other headers, so a URL instance with a plain header and an
  OAuth config called without its token. They are always merged now
  (`callSetup`; covered by `TestCommandInstanceVerifiesThroughTheGatewayAndSignsCalls`).
- mcpclient: `IsTransient` does not count a refused address
  (`netguard.ErrUnsafe`) or a non-timeout url.Error as transient, so a guard
  refusal fails a verification at once instead of retrying for 600 s (`TestIsTransient`).

- Run tools: tool_manager.py `_discover` (via ToolBuilder.add_explicit)
  appended every attachment's tools, so two attachments offering the same
  model-facing name (two OpenAPI connections with an operation `list`, a
  code toolset and an operation) sent duplicate functions and the model
  provider refused every call of the run. Resolution now fails final
  (`ErrToolsRefused`) naming both (`TestRunToolsRefusesADuplicateToolName`).
  An MCP-vs-MCP clash (tool_builders.py:77) was a retryable ValueError; it
  is the same final refusal.

Security review fixes (2026-11-15):

- Run tools: an OpenAPI config with no `openapi_connection_id` was resolved
  by name (or an id in its name) across the workspace with no permission
  check (`tool_manager.py:242` `_resolve_openapi_connection`, past
  `config.py:107` `_tool_connection`), and nothing checked at call time, so a
  run could call through someone's personal connection with their OAuth
  token. Resolution now takes only a connection the agent holds
  `use_connection` on or the platform manages (`agentMayUse`, the same test
  `requireUsable` makes), refusing a match it may not use; `CallOpenAPI`
  re-checks it per call from `OpenAPICall.AgentID`, which `app/runs_ports.go`
  now passes (`TestRunToolsOpenAPIResolvesOnlyConnectionsTheAgentMayUse`,
  `TestCallOpenAPIRechecksTheAgentMayUseTheConnection`).
- Tool policy: OpenAPI operations have one identity on every path into the
  PDP, `OpenAPIToolNames` (allowed only by `openapi:<connection>:<tool>`;
  the tool, operation, connection name and id only deny or hold). The
  per-connection proxy judged by the bare name with the name allowing it
  (`client_mcp.py:549` `_name_allows`, no aliases on that scope), so a rule
  on the canonical target never matched and a bare-name allowlist entry
  allowed the operation on any connection; run bindings now carry the same
  restricting names. A client bundle's OpenAPI call went through the
  proxy's check, skipping the bundle verdict and the audit row (Python
  audited it); it is now judged and audited like every bundle call, with
  `openapi_connection_id` in the row (`TestCallConnectionToolJudgesTheCanonicalIdentity`,
  `TestClientEndpointJudgesAndAuditsOpenAPICalls`).
- Docker runtime: the manager defaulted `AGENTAREA_MCP_NETWORK` to
  `agentarea_default` (`agentarea-mcp-manager/internal/config/config.go:146`),
  the compose network with Postgres, Valkey, Hydra admin and OpenFGA. The
  default is now `agentarea_mcp-network` (what both compose files already
  set and declare, the gateway dual-homed), and the backend refuses `host`
  or any `*_default` network; the suite stack sets `${project}_mcp-network`
  (`TestBackendRefusesThePlatformNetwork`). Kubernetes needs no change: the
  chart's `mcp-instances-ingress` admits only `component: mcp-manager` pods
  and `mcp-instances-egress` denies RFC1918 + link-local (pods selected by
  the `managed-by: mcp-manager` / `component: mcp-server` labels the kube
  backend keeps). When the Go `mcp` role gets its chart, its pod must carry
  `app.kubernetes.io/component: mcp-manager` or instances refuse it.
- Runtime spec: only `agentarea.io/egress` was dropped from `json_spec.labels`
  (`kubernetes_resources.go:159` copied the rest), so a spec could stamp
  `agentarea.io/dataplane-id` and pass as another data plane's workload on a
  shared cluster. Every `agentarea.io/` label is dropped now, before the
  deployment hook (`TestEnvironmentResolvesSecretsLabelsAndKeys`).
- `POST /oauth2/register` (anonymous) read its body unbounded
  (`mcp_oauth_as.py:297`); it caps at 64 KiB with a 413. Every other
  connections route is mounted on the serve mux, which `serve.Assemble`
  wraps in `httpx.Chain` (`LimitBody`, `AGENTAREA_API_MAX_BODY`); the
  gateway (32 MiB), storage (`maxSize`) and data-plane host (1 MiB) cap
  their own.
- Per-connection proxy: an OpenAPI call through the connection's MCP proxy is
  audited again as Python's `_governed_call` did (`client_mcp.py:1031`): one
  row per verdict against `openapi_connection`/<id>, actor `client` or
  `user`, argument keys only, before the call runs; the bundle and the proxy
  share `auditToolCall` (`TestCallConnectionToolIsAudited`).
- MCP calls: Python checked `use_connection` only at resolution
  (`config.py:124` `_require_usable_connections`, `:157`
  `_require_selectable_connection`); `tools.py` never re-checked, so a
  connection withdrawn mid-run stayed callable. `MCPTools.Call` re-checks the
  instance the binding names each call: the agent's right, else the run
  user's (an instance selected for the run), a platform instance excepted;
  a refusal is a failed result, not stamped as a dispatch
  (`TestMCPCallRechecksUseAtCallTime`).

## Kept bugs

- Instances: POST /{id}/test-auth still only answers "pending"; nothing tests
  the auth.

## Deviations

- MCP surfaces (`/mcp`, `/mcp/w/{workspace}`, `/mcp/clients/{id}`,
  `/client-mcp/{id}`, an API connection behind `/v1/mcp/{id}/mcp`) answer
  JSON only, never SSE; GET is 405. Python's stateless mounts streamed SSE
  when Accept allowed it.
- `/mcp/clients/{id}`: members are discovered one after another (Python
  gathered them) and their tool lists are not cached in Redis. An attached
  OpenAPI operation is delegated to `CallConnectionTool`, so its audit row
  names the openapi_connection, not the client. A call the policy holds for
  approval is refused with the policy's reason.
- Proxy: a demand-gateway instance that does not start within
  `GatewayStartWait` answers 502 "Upstream MCP error: ..." (mcpclient's
  GatewayRetry) where Python passed the gateway's 503 through.
- The MCP Events extension is not advertised: no events/* method is served here.
- Platform toolset tools carry the contract's name, description and input
  schema, a title and effect-derived annotations, but no outputSchema; the
  structured content is the value (a list wrapped as {"result": [...]}) and
  the text is compact JSON with RFC 3339 times (Python: str(datetime)).
- skills_import_from_github finds SKILL.md candidates in the downloaded
  zipball instead of the GitHub tree API, reads frontmatter name and
  description as top-level scalars, and names the zipball's commit in a raw
  URL when the GitHub URL names no branch.
- A platform tool's pydantic ValidationError text (`N validation errors for
  Model` + loc + msg [type=...]) leaves out `input_value` and the docs URL.
- audit_list `since`/`until` accept the RFC 3339 / ISO forms Go parses;
  Python's fromisoformat accepts a few more (e.g. week dates).
- workspace_files_list content_type is the stored object's type, else the
  extension's (sandbox ContentTypeOf).

- Instances: MCPValidationError (422) is a problem body, detail = errors joined
  by "; ", plus an `errors` list extension (what the webapp's formatApiError
  reads).
- Instances: `json_spec.env_vars` is sorted; Python kept dict insertion order.
- Instances: lone surrogates in json_spec are not refused (Go's decoder already
  replaced them); only NUL is.
- Instances: a `settled` cost source gets the generic "a connection's own cost
  is a rate, a reported field or free, not settled".
- Instances: POST /check `status_code` is always 400 for an invalid answer (the
  runtime port carries no manager status).
- Instances: GET /health/containers reports `error` where Python said
  `manager_unreachable`; a missing workload is `not_running`.
- Instances: POST /with-spec errors in the instance part are 400 with one
  message, not Pydantic 422 entries.
- Instances: a failed synchronous verify after a URL create is logged, the
  create still answers 201 with the stored verification.
- Instances: egress exits are refused ("egress exits need the enterprise
  edition") until the enterprise extension is ported.

- OAuth: platform-managed credentials are read from `service.PlatformWorkspace()`
  (id "platform"); callers of `AuthHeaders` for a managed config pass that
  workspace. Python read the caller's workspace and answered {}.
- OAuth connect: the workspace slug rides in the OAuth state
  (`workspace_slug`); finish takes it from the entered workspace, receive
  without one sends the browser to the workspace-gone landing.
- OAuth connect and AS shim are plain chi routes (redirects, raw proxying), not
  the generated strict operations. They mount only with KV, Out and OAuthStore
  (connect) / Out (shim) wired.
- OAuth AS: `/.well-known/oauth-authorization-server`, the DCR post and the
  Hydra proxy answer 502 "Authorization server unavailable" when Hydra is
  unreachable (Python 500). Hydra discovery is cached after the first success.

- OpenAPI writes are plain chi routes (`handlers/mount_openapi_writes.go`) and
  mount only when OpenAPIWrites, Out, Secrets and Graph are wired. An address
  the guard refuses is a 400 in netguard's wording; Python returned a pydantic
  422 or 400 with its own text.
- OpenAPI: a YAML spec's non-string keys are stored as text. Anchors, aliases
  and merge keys are refused, and the YAML is bounded at 2M nodes and depth 128.
- OpenAPI: an operation's response is read up to 32 MB; the tool result is
  cut at 64 KB as before.
- OpenAPI: the connection list and detail read sharing in one batch
  (`SharingOf`).

- MCP client (`mcpclient`): own Streamable-HTTP + legacy SSE client over a
  caller's RoundTripper; no MCP session pool, one connection per tool call
  (the per-call context and no-shared-credentials rules still hold). A
  workload is reached in process through `HandlerTransport(Runtime.Gateway())`.
- Verification runs under `context.WithoutCancel`, so a dropped request still
  leaves the row in a terminal state.
- Structured content used as the text result is JSON, not Python's repr.
- Platform-managed URL instances dial with `netguard.Internal` in
  `UpstreamFor`, as execute_tool did; Python's proxy pinned them as Member.
- Package-import candidates: `mcp_servers` is catalog's, so the query reads
  only instances (200 per tick) and the npx/uvx filter runs in Go via `Specs`;
  more than 200 non-npx candidates ahead of an npx one delay it.
- Verify / discover-tools / validate / validate-connection / probe are plain
  chi routes (`handlers/mount_verify.go`). A probe of an unknown instance is
  400 "Instance not found" as before; `requires(edit)` usually answers first.
- `DiscoverTools` on the service is the OpenAPI one; the MCP instance's is
  `DiscoverInstanceTools`.

## Runs adapter

`connections.Module.OpenAPITools()` returns an `api.OpenAPITools`. The runs
orchestrator maps its `ToolInvocation` onto it this way:
`OpenAPICall{UserID: inv.Principal (user id), ConnectionID:
inv.Binding.OpenAPI.ConnectionID, Operation: inv.Binding.OpenAPI.OperationID,
Args: inv.Args}`. The result `OpenAPIResult` becomes `ToolOutput{Success,
Result, Error, MeteredBody: Body}`. A success is stamped on
`openapi_connections.last_dispatch`. Governance stays with the orchestrator
(its PDP); `CallOpenAPI` does not judge the call.

`connections.Module.MCPTools()` returns an `api.MCPTools` (it reads the
module's current Service per call). `ToolInvocation` maps to
`MCPCall{WorkspaceID: inv.Principal.WorkspaceID, UserID: inv.Principal.UserID,
AgentID: inv.Principal.AgentID, TaskID: inv.TaskID, ToolCallID: inv.ToolCallID,
InstanceID: inv.Binding.MCP.InstanceID, Tool: inv.Binding.MCP.RawName, Args:
inv.Args, TaskMetadata: inv.RunMetadata, Progress: <the run's progress sink>}`.
connections re-resolves the URL, transport and secrets itself; the binding's
URL/Transport/EnvSecretNames are not trusted. `MCPResult` becomes
`ToolOutput{Success, Result, Error, ServerInstanceID, StructuredContent,
StructuredContentDropped, Images, MeteredMeta: Meta}`; a
failure is a result with Success false, never a Go error (a Go error is
infrastructure). A bundle routes to its member by tool name.

Lifecycle: the worker must start `Module.Monitor()` (stale verifications,
never-attempted sweep, package imports). Every process that calls tools (API
and worker) must start `Module.DispatchStamps()`, or last_dispatch is never
written (the queue drops when full).

## Blocked / not ported

- OpenAPI: a direct `CallConnectionTool` call (`/v1/mcp/{id}/mcp`, client
  bundles) has no approval link, audit row, spend cap or metering. A call the
  policy holds for approval is refused with the policy's reason.
- OpenAPI: catalog_connector / catalog_spec (the registry_items metering
  reads) belong to runs metering and are not ported. Cost-declaration payer
  checks (`CheckPayers`) are not run on create.

- `/mcp/clients/{id}`: approval of held calls, spend caps and cost_entries
  (runs owns cost_entries) for client tool calls.
- MCP Events server side (mcp_events.py): streams.
- Platform toolsets: every tool of mcp-tools.json not named in
  `api/contract/tools-pending.txt` is served (registry_test.go holds the
  contract and the ratchet).
- Platform resources (ui://) and prompts: `prompts/list` is empty and the
  platform mounts serve no resources.
- OAuth connect: `service.Deps.CatalogItems` (a registry_items API-item read)
  is nil: catalog/api has no such read. Preflight/authorize for
  `catalog_item_id` answer 503; creating the pending openapi_connections row
  from a catalog item also waits on the OpenAPI create path. Reconnecting an
  existing connection works.

## Run tools (runs' RunDefinitions.Tools)

`Module.RunTools()` returns `api.RunTools`; `RunTools(ctx, api.RunToolsRequest)`
is `service.(*Service).RunTools` (`service/runtools.go`), the resolution of
config.py `_resolve_task_resources` (agent `use_connection` per connection,
platform-managed exempt; selected MCP instances visible and usable by the
starter, a config naming one by name bound to its id with its restriction)
and ToolManager `discover_available_tools_split`, `discover_tool_providers`
and `openapi_operation_tools` in one read. `api.RunToolSet` has the same
fields as runs' `service.ToolSet` (struct conversion).

- MCP: the instance's pinned snapshot (`tools`, legacy
  `json_spec.available_tools`) only when verification succeeded (bundle:
  derived from members). An instance with no snapshot (tools NULL) is
  verified once at resolve time, which lists tools over MCP and pins them
  (ADR-0032); a platform-managed one is skipped. App-only tools
  (`_meta.ui.visibility` without model) are dropped; `allowed_tools` nil =
  all, [] = none; names `mcp__<label>__<raw>`, same-named servers get an id
  suffix. PolicyNames `mcp:<id>:<raw>` (+ attachment ref), RestrictingNames
  `mcp:<instance name>:<raw>`, raw.
- OpenAPI: by `openapi_connection_id`, else exact name; stored operations
  narrowed by `allowed_tools` (raw names); `load_mode: searchable` puts them
  in SearchableTools (binding still set) instead of Tools.
  OpenAPIOperationTools maps the attachment name to every operation tool.
- Code: `agentarea/files`, `agentarea/shell` (schemas in
  `service/codetools.go`) and the platform toolsets of mcp-tools.json
  (`platform_pinned`), one tool per method: the toolset name for a
  one-method toolset (`shell`), else `<toolset>_<method>`; disabled_methods
  dropped. PolicyNames are the namespace and the toolset name.
- ToolProviders: one per attachment (MCP named by its server label).
- Not offered: math/web/media/context/triggers code toolsets (no Go
  callers yet; logged as unknown), remote A2A delegates (`agent` with
  a2a_url), connector cost declarations (`Binding.Cost`), Method/Path of
  OpenAPI bindings (connections re-resolves at call time).
- Platform toolset tools run through `Module.PlatformTools()` (app's
  `Tools["code"]` caller): the same registry as `/mcp/w/{workspace}`, called
  as the run's agent in the run's workspace, so per-tool admin checks refuse
  it exactly as they refuse an agent over MCP.

Deviation: code toolsets are one model tool per method with unprefixed
arguments (Python: one tool per toolset with an `action` enum and
`<method>_<arg>` arguments), which is what runs' code callers read.

### Wiring needed

`app/worker.go` `workerRuns`: build connections with the graph
(`connections.New(connections.Deps{DB: d.DB, Graph: d.Graph, Specs: catalogMod.MCPSpecs(), Runtime: <in-process MCP runtime>, Out: d.Outbound, Secrets: secrets.NewSession(d.Secrets), Log: d.Log})`;
Specs/Runtime/Out are needed only to pin an unpinned instance) and give the
runs RunDefinitions composite this Tools method (rule 1 keeps runs'
Principal/ToolsRequest/sentinels out of connections):

```go
type runTools struct{ t connectionsapi.RunTools } // t: connectionsMod.RunTools()

func (r runTools) Tools(ctx context.Context, p runsservice.Principal, req runsservice.ToolsRequest) (runsservice.ToolSet, error) {
	ts, err := r.t.RunTools(ctx, connectionsapi.RunToolsRequest{WorkspaceID: p.WorkspaceID, UserID: p.UserID, AgentID: p.AgentID,
		TaskID: req.TaskID, Agent: req.Agent, MCPInstanceIDs: req.MCPInstanceIDs})
	switch {
	case errors.Is(err, connectionsapi.ErrToolsNotFound):
		err = errors.Join(runsservice.ErrNotFound, err)
	case errors.Is(err, connectionsapi.ErrToolsRefused):
		err = errors.Join(runsservice.ErrRefused, err)
	}
	return runsservice.ToolSet(ts), err
}
```

## Agent loans (agents' Connections)

`api.Loans` (`Module.Loans()`, `service/loans.go`): `BindMCPName` is `_bind_mcp_tools`' name lookup
(the one visible instance named so, the caller's or the platform's; else `MCPNameError` when
refused), `Lend`/`Withdraw` are `lend_connection`/`withdraw_connection` (`connection_user` tuple).

## An agent and auth configs (2026-11-15)

`GetAuthConfigForUse` let an agent attach its starter's auth config to a
connection it then owned, because it matched `CreatedBy` against the starter's
user id. An agent subject now uses a config only when the graph lends it
(`use_connection` on the config, the rule of `execute.go`), never by its
starter's authorship or admin rights. Test:
`TestAnAgentUsesOnlyAnAuthConfigLentToIt`.

Toolset bounds: `agents_list`, `clients_list`, `projects_list`,
`openapi_connections_list` and `triggers_list` clamp `limit` to 1..1000;
`runs_get_events` and `triggers_get_history` to 1..100; `workspace_files_list`
clamps `max_items` to 1..10000 (MAX_LISTED_FILES); `skills_get_file` clamps
`expires_in` to 60..86400. Python took any value; the bounds are those of the
HTTP routes each tool mirrors. The schemas are unchanged.

## Paying a 402 (`payment/`, runs' calls)

`mcp_payment_httpx.AgentAreaPaymentTransport` and the OpenAPI `payment_handler`
(`activities/agent/tools.py`, `payment_handler.handle_402_payment`, `libs/payment`)
are one `payment.Session` per run call: `Wrap` sits over the call's netguard
transport (MCP `callSetup`, OpenAPI `callOperation`), so the signed retry and the
MPP chain RPC (`netguard.Member`) go through netguard too. On a 402 it detects the
protocol, reads the agent's active wallet once, keys the payment
`walletapi.IdempotencyKey(callRef, seq)`, skips a key that already settled, quotes
and checks the challenge, `Reserve`s, signs, retries, then `Complete`s or `Fail`s.
`MCPResult.Payments` / `OpenAPIResult.Payments` carry the payments to runs' meter
(`app/runs_ports.go`). Wallets come from `Module.UseWallets` (app, after wallet).
Vendor settlement for runs is `Module.SettledCosts()` (`service/settlement.go`).

Fixed Python bugs:
- The budget check and the payment record were separate statements, so parallel
  calls of one agent could all pass the check and overspend. `Reserve` holds the
  amount under the wallet lock (wallet PORTING-NOTES, its concurrency test), and
  the transport pays only after it (`TestSessionRefusesPastTheBudget`).
- x402 v2 receipts name the transaction `transaction`; Python read `txHash` /
  `transaction_hash` only, so v2 payments were recorded without a tx hash and,
  on a failed answer, as `failed` although the money left. `Receipt` reads
  `transaction` first. Tests `TestSessionPaysA402AndReplaysTheRequest`,
  `TestSessionCountsMoneyThatLeftOnAFailedAnswer`.
- `mpp_config.session_budget_usd` was not enforced on the MCP path. The quote's
  limit refuses a larger amount on both paths before reserving, test
  `TestSessionRefusesPastTheMPPSessionBudget`.

Deviations:
- A budget refusal records no `failed` payment row (Reserve inserts nothing);
  the refusal is in the call's payments and the tool error.
- A paid retry that fails in transit keeps its reservation pending (the server
  may have settled). The signed payment is stored on the hold (`Wallets.Sign`)
  before it is sent, and a retried activity, which reaches the same hold under
  the same key, sends that payment again unchanged instead of signing a second
  one (x402 nonce, Tempo chain nonce). A replayed payment the answer does not
  settle stays held. A retry whose challenge asks more than the hold is refused.
  Tests `TestARetriedCallSendsTheSamePaymentAgain`,
  `TestARetryAskingMoreThanItsHoldIsRefused`,
  `TestASentPaymentThatIsRefusedOnReplayStaysHeld`.
- Python paid any asset a challenge named and read its amount as six-decimal
  USD. x402 pays only the network's USDC (`x402DefaultAsset`, x402's
  NETWORK_CONFIGS); MPP only Tempo's USD stablecoins (pympp `_defaults`: USDC
  and pathUSD on mainnet 4217, pathUSD on testnet 42431) on the chain the
  charge goes to, and refuses `mpp_config.decimals` other than 6. Python's
  `mpp_config.currency` is a default for the server side of pympp, not a
  client allowlist, so it is not read. Tests `TestX402PaysOnlyTheNetworksUSDC`,
  `TestMPPPaysOnlyTempoUSDStablecoins`.
- An OpenAPI paid answer goes through the ordinary response decoding
  (response_transform, metering); Python returned the paid body raw.
