# catalog: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/catalog.md`.

## Mounted (31 of 41 operations)

registries: list, create, get, patch, delete, items list, item create, item patch,
item delete, catalog search, item update-spec, update-all, sync. workspace-registries:
list, get, create, patch, delete, sync. Sync, delete and retire mount only with
`Deps.Uses` and `Deps.Net`; workspace sync also needs `Deps.RateLimit`. provider-specs: list, with-models, get, by-key.
model-specs: list, get, by-provider, by-provider/{name}, create, patch, delete,
upsert. Implemented, not mounted until `Deps.Connections` and `Deps.Pricing` are
wired: catalog browse, catalog item get. `Module.Specs()` (catalog/api.Specs)
serves models; `Module.UseModels(models.SpecUse())` hands back models' spec use
(models is built after catalog), and the provider lists mount only with it.

Wiring: `Admin` (requires_workspace_admin) gates the model-spec and
workspace-registry writes as a route dependency, before validation, like
`platformWrite`. `Secrets` binds the cluster secret catalog per caller (no
auditor: get_for_use / add_reference / clear_references write no audit row).
`Guard` is the outbound address policy behind `_require_public_https`. `APIURL`
builds `icon_url` (build_icon_url, namespace `providers`).

## Blocked / not ported

- Browse and item get: a connection's card needs `readable_catalog_connections`
  (connections + the graph's readable ids) and `price_catalog_items` (billing
  quote, compute estimate). Ports `service.CatalogConnections` and
  `service.CatalogPricing`; connections/api has only `Lookup`, billing exposes no
  quote: both stay nil in app.
- Item update-spec / update-all port the API process's `RegistryService` (no
  provider or model spec repository, `libs/registry/agentarea_registry/application/service.py:1396-1440`):
  mcp_servers items rewrite the installed `mcp_servers` row (catalog's table),
  llm items refuse with 400, the rest do nothing.
- mcp-servers (6): the graph's readable ids, the PDP, the governance audit writer,
  events, and `libs/mcp` projections (connections). bundles analyze/install:
  agents, governance, connections and streams. There is no `fmt` route.

## Fixed Python bugs

No client reads the changed behaviour: the webapp calls with-models,
provider-specs list/get and model-specs upsert only; nothing in
`agentarea-webapp/src` or the CLI calls catalog search, model-spec
list/get/create/patch or matches the item-write message.

- Search pages after the `tag` filter, in SQL; Python filtered the page, so it
  came back short or empty while later pages matched
  (`libs/registry/agentarea_registry/infrastructure/repository.py:962`). Test:
  `store.TestSearchFiltersBeforePagingAndSkipsInactive`.
- Search leaves out items of inactive registries and items gone from their source
  (`registry_active`, which folds `in_source`), as browse does
  (`infrastructure/repository.py:934-960`). Same test.
- `created_at`/`updated_at` written by catalog are UTC, so the `Z` they are
  rendered with is true; Python wrote the process's local wall clock
  (`libs/common/agentarea_common/utils/types.py:16`). Test: `store.TestTimestampsAreUTC`.
- Update and delete of a catalog item say "written to a managed registry", as
  create does; Python said "written in"
  (`libs/registry/agentarea_registry/application/service.py:849,878`). Test:
  `service.TestCreateCatalogItem`.
- `models` in with-models, get and by-key are the caller's workspace's model
  specs; Python listed every workspace's rows, which ProviderConfigForm offered
  as models (`apps/api/agentarea_api/api/v1/provider_specs.py:132`). Test:
  `store.ModelSpecsOfProviders` filters by workspace (`queries/specs.sql`).
- POST `/model-specs/` and `/model-specs/upsert` with an unknown
  `provider_spec_id` answer 404 "Provider specification not found"; Python
  answered 409 "already exists" (create, `model_specs.py:235-241`) or 500 (upsert).
  Only a unique violation is a 409. Tests: `service.TestCreateModelSpecRefusals`,
  suite `TestModelSpecOnAnUnknownProviderIs404`.
- PATCH `/model-specs/{id}` on a catalog projection answers 404, as DELETE does;
  Python wrote nothing and answered 200 (`model_specs.py:259-268`). Test:
  `service.TestCatalogProjectionsAreReadOnlyAndNeedTheirProvider`.
- A catalog model whose provider is not installed is not listed or found; Python
  rendered it with `provider_spec_id: "None"` (`model_specs.py:95`), a string the
  schema declares a UUID. Same test.

## Kept

- POST `/registries/` answers 200, POST `/workspace-registries` 201; item delete
  204, registry delete `{"status":"deleted"}`
  (`apps/api/agentarea_api/api/v1/registries.py`): the published OpenAPI and the
  generated clients key on these codes.
- Item update-spec of an llm_providers / llm_models item answers 400 "Provider spec
  repository not available" / "Provider and model spec repositories required"
  (`libs/registry/agentarea_registry/application/service.py:1633,1678`): only sync
  installs LLM items as entities.

## Deviations

- PATCH `/registries/{id}` with `name`, `source_url`, `is_active`, `mode` or
  `trust` set to null: Python writes NULL and the NOT NULL constraint answers 500;
  Go writes the zero value. Item PATCH with `spec` or `tags` null writes `{}` / `[]`.
- FastAPI parses the JSON body before route dependencies, so malformed JSON
  answers 422 to a non-platform caller; Go refuses with 403 first.
- `domain.Casefold` covers the letters `str.casefold` folds beyond `lower()` that
  catalog names carry (ß, ς, ligatures, ſ, µ), not the full Unicode table.
- Discovery upsert (`UpsertModelSpecs`) issues one statement per row, not
  executemany.
- The model-spec list's own rows come back newest first; Python re-selects them
  with `WHERE id IN (...)`, which has no order
  (`libs/llm/agentarea_llm/infrastructure/model_spec_repository.py:184-189`).
- PATCH `/workspace-registries/{id}` with `name` or `is_active` null answers 409
  without writing (Python's flush hits NOT NULL, also 409) after the same source
  validation.

## MCP specs for connections

`Module.MCPSpecs()` (`api.MCPSpecs`, `service/mcp_specs.go`, `store/mcp_specs.go`)
is the part of `MCPServerRepository` connections uses, so that connections never
queries `mcp_servers` itself. `Get` follows `get_server_by_id`:
1. the workspace's row;
2. a platform mirror of an item of an active registry (`Catalog`);
3. with `PlatformBacked`, a platform row, because the caller checked the connection is platform-managed;
4. the read-only projection of the registry item (`Projection`).

Rows built from a catalog item get `_hydrate_catalog_env_schema`.

`Create` and `MaterializeCopy` insert in the caller's tx under a slug unique in
the workspace (`scope.UniqueSlug`; exhaustion is `*api.ErrSlugsExhausted`).
`SetAuthMethods` is the probe's `json_spec.auth_methods` cache, and it writes only the workspace's own rows.
JSON columns decode with `json.Number`, into plain `map[string]any`/`[]any`.
`NormalizeMCPEnvSchema`/`DeriveMCPEnvSchema` are the plain-JSON twins of the wirejson versions in `service/mcp.go`.

## Sync and reconcile (2026-11-14)

`service/parse.go` (index parsers, untrusted JSON/YAML), `service/source.go`
(URL index HEAD/GET through `netguard` Vendor/Member transports, GitHub REST with a
token, git smart-HTTP ls-refs + codeload archive without), `service/github_index.go`,
`service/sync.go` (SYNC_FORMAT "7" ETag, item diff, entity materialisation,
retire, pointer checks, `sync_error_message`), `service/reconcile.go`,
`store/sync.go` (catalog tables only). Foreign rows go through `api.ItemUses`.
Tests: `service/sync_test.go` (parsers, caps, git tree ids checked against an
independent hash, error classes), `service/sync_db_test.go` and
`store/sync_test.go` (postgres), `handlers/sync_test.go` (502 / 400 / 429 / ports),
suite `TestSyncAndRemoveNeedTheRightCaller`.

Deviations:
- The MCP mirror row of an item is always written to the platform workspace;
  Python wrote it with the session's context, the caller's workspace when the
  route triggered a sync.
- Dropping a legacy platform skill row goes through `ItemUses.DropPlatformSkills`
  from every sync; Python skipped it (keeping the row) outside the platform context.
- A platform source is capped at 64 MB and parsed by the same alias-free YAML
  walker as a workspace source (10x the node cap); Python used `yaml.safe_load`.
- `RetireRegistry` runs in one transaction; Python committed per step.
- Reconcile is `Module.Reconcile()` (`api.Reconciler`): it takes parsed manifest
  entries and returns `api.ReconcileResult`; reading REGISTRIES_CONFIG /
  `--config-file` / `--source`, printing and the exit code (1 when `Failed` is
  non-empty) are the operator role's. No graph client registration: no skill row
  is created by sync any more.
- `domain.RegistryPatch.SourceType` exists for reconcile only (no HTTP body sets it);
  setting it clears the stored ETag.

## Wiring (2026-11-15)

app/catalog_ports.go wires `Uses` (agents `CatalogUses`, connections `CatalogUses`,
models `SpecUses`, resolved at sync time because models is built after catalog),
`Net` (cluster Outbound), `RateLimit` (Valkey), `Credentials`
(registry_credentials_resolver: the secret row of the registry's workspace, its
value from that workspace's backend as the platform principal) and `PlatformSecrets`
(platform_secret_id by id or name; the registry recorded as consumer `registry`,
field `credentials`). Sync, retire and workspace sync are mounted.
Mirror: agents `CatalogMirror()` (store_catalog_item per item; a GitHub-pointer item of a
registry with credentials fails loudly, only public repositories are read; a rate limit stops
the rest of the sync's GitHub reads). `Installs()` serves agents' presets, installs and run
provenance; `Folder` reads a skill folder at its pin over the commit archive.
Still nil: `Connections` and `Pricing` (browse and item get stay unmounted:
connections has no readable catalog-connection card read, billing no quote and the
MCP runtime no instance reservation). `MCPInventory()` serves identity's explorer.

## Wiring needed (as the porter left it)

`catalog.Deps` gained (all nil-safe: the routes and `Reconcile` refuse or stay
unmounted without them):
- `Uses api.ItemUses`: composed from agents (skills forks + legacy platform skill
  delete, agents.registry_item_id), connections (mcp_server_instances.server_spec_id,
  openapi_connections.registry_item_id) and models (provider_configs, model_instances
  use checks). Runs in the sync's transaction, across workspaces.
- `Net netguard.Clients` (profiles/cluster/netguard.Outbound); `GitHub` zero = github.com.
- `Mirror api.ContentMirror` (agents' skill content store, ADR-0044) for mirror-mode
  skills registries.
- `Credentials api.RegistryCredentials` (secret value by workspace + id at sync time).
- `PlatformSecrets api.PlatformSecrets` (platform secret id by id or name; record the
  registry as consumer).
- `RateLimit httpx.RateLimiter` (Valkey token bucket) for workspace sync.
- `Connections` and `Pricing` still mount browse and item get.
- The `operator` role calls `catalog.Module.Reconcile().Reconcile(ctx, api.ReconcileOptions{...})`.
