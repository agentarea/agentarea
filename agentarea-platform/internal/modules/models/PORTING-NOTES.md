# models: porting notes

Python paths are relative to `agentarea-platform/`.

## Ported

All 17 operations of `api/openapi/models` (provider-configs, model-instances, pricing), the
model caller and resolver runs uses (`api.Caller`, `api.Resolver`), `api.SpecUse` for catalog,
and the transports of `libs/agentarea-agents-sdk/agentarea_agents_sdk/models/llm_model.py`
(OpenAI-compatible and Anthropic: streaming, tool calls, reasoning, usage and cost).
Failure classification is `libs/execution/agentarea_execution/llm_failures.py`. Retries are
Temporal's, through the `ApplicationError` type and non-retryable flag `CallFailure` sets.

## Fixed Python bugs

- Config and instance lists come back newest first. Python lost the `created_at DESC` order
  in the relationship reload (`libs/llm/agentarea_llm/infrastructure/provider_config_repository.py:125`,
  `libs/llm/agentarea_llm/infrastructure/model_instance_repository.py:95`).
  Test: `store.TestListsAreNewestFirst`.
- `model_instance_ids` counts only the caller workspace's instances of the configuration.
  Python listed every workspace's, which leaked tenants' choices on the platform config
  (`apps/api/agentarea_api/api/v1/provider_configs.py:101`). Test: `store.TestInstances`.
- Sending `name`, `is_active` or `is_public` as null on update leaves the field unchanged.
  Python answered 500 on the NOT NULL violation
  (`libs/llm/agentarea_llm/application/provider_service.py:301`).
  Test: `service.TestUpdateConfigClearsAndReplacesTheOwnSecret`.
- The logo key is `^[a-zA-Z0-9_-]+$` with no trailing newline. Under Python's `re.match`,
  `$` also matched before a final newline, so `openai\n` was served default.svg
  (`apps/api/agentarea_api/api/v1/provider_configs.py:699`). Test: `handlers.TestProviderLogo`.
- A run's model call is refused when the instance or its configuration is inactive.
  Python resolved it anyway (`libs/execution/agentarea_execution/activities/agent/llm.py:161`).
  Test: `service.TestModelResolution`.
- `provider_display_name` is the provider spec's name. Python read the spec's
  `display_name`, which has no such attribute, so it was always None
  (`libs/execution/agentarea_execution/activities/agent/llm.py:213`).
  Test: `service.TestCallStreamsAccumulatesAndBills`.

- A platform-supplied config only carries a platform-owned spec of its own provider. This is
  checked at create, and in `Model()` for rows that already exist. Python let a workspace
  attach its own spec, priced as it liked (0 included), to a platform config, which gave
  free calls on the platform's key (`apps/api/agentarea_api/api/v1/model_instances.py:132`,
  `libs/execution/agentarea_execution/activities/agent/llm.py:161`). No client creates
  instances on a platform config: the webapp shows those configs read-only.
  Test: `service.TestAPlatformConfigTakesOnlyThePlatformSpecsOfItsProvider`.
- Instance reads widen only to instances owned by the platform workspace. Python widened
  them to any instance on a platform config, so it listed, fetched and resolved other
  workspaces' instances, and those shared the 100-row limit
  (`libs/llm/agentarea_llm/infrastructure/model_instance_repository.py:35`).
  Test: `store.TestOnlyThePlatformWorkspaceInstancesWidenReads`.
- A model call is bounded:
  - a 10-minute overall deadline on top of the 300 s idle timeout;
  - 64 MiB per answer, 4 MiB per stream line;
  - for `/model-instances/test`, 60 s and 1 MiB.
  A discovery listing is capped at 8 MiB (it was 64 MiB). Python read without bounds
  (`libs/agentarea-agents-sdk/agentarea_agents_sdk/models/llm_model.py:648`,
  `libs/llm/agentarea_llm/application/model_discovery_service.py:191`).
  An oversized answer fails with a non-retryable `ResponseTooLarge`.
  Tests: `transport/limits_test.go`, `service.TestTheTestRouteCutsAnEndlessAnswer`,
  `service.TestDiscoveryRefusesAnOversizedListing`.

## Kept

- `discover-preview` writes the discovered specs: it is not a dry run
  (`apps/api/agentarea_api/api/v1/provider_configs.py:419`). The webapp relies on this.
  `ProviderConfigForm/components/ModelInstances.tsx:122` previews, refetches the specs and
  bulk-creates instances by those `model_spec_id`s.
- `model_instance_ids` holds model spec ids, not instance ids.
  `agentarea-webapp/src/lib/api.ts:2507` matches them against the provider's models.
- `/provider-configs/with-instances` answers `ProviderConfigResponse`: that is the declared
  `response_model` and the OpenAPI contract
  (`apps/api/agentarea_api/api/v1/provider_configs.py:262`).
- `is_public` is stored and returned but never consulted. No visibility rule exists to
  restore, and the webapp sends and shows the flag.
- Instance DELETE is member-level, like create. `require_permission` names `model_instance`,
  a type the graph does not govern (`apps/api/agentarea_api/api/v1/model_instances.py:280`).

## Differences

- `/model-instances/test` resolves the spec with `UsableModelSpec` only. Python's
  `get_model_spec` also falls back to a catalog item; the catalog API has no projection
  for it, so a catalog item id answers 404 "Model spec not found" here
  (`apps/api/agentarea_api/api/v1/model_instances.py:319`).
- A key set through an Infisical-backed secret manager is not rolled back when the config
  insert fails; Python commits it in the same order.
- `str(dict)` in a stream error message and `json.dumps` of a tool result order a dict's
  keys `type`, `text`, `image_url`, `url`, then sorted: the decoded object's own order is
  not kept.
- Python's UTF-8 `errors="replace"` gives one U+FFFD per maximal invalid subpart; Go gives
  one per invalid byte, which differs only for truncated multi-byte sequences.

## Wiring (`app/serve.go`)

- `coreDeps.Outbound *netguard.Outbound`, built in `runServe` from `netguard.LoadConfig`,
  `LoadTrust(ExtraCACerts)` and the cluster `netguard.New`.
- The models constructor line after catalog, and `modelsMod.Serve()` in the slice. Secrets go
  through `profiles/cluster/secrets.NewSession(coreDeps.Secrets)`. Pricing is read lazily
  from `coreDeps.Extensions.CustomerPricing`. `AGENTAREA_LOCAL_HOST` is read as Python's
  `AppSettings.local_host` (`libs/common/agentarea_common/config/app.py:161`).

## For catalog sync (2026-11-15)

`SpecUses()` (`api.SpecUses`): which provider specs a provider config is on and which
model specs a model instance runs on, across workspaces, in the sync's transaction.
