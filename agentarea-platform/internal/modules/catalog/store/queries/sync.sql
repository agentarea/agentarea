-- Catalog sync (RegistryService.sync_registry, retire_registry): catalog-owned tables only.

-- name: PlatformRegistryByName :one
SELECT * FROM registries WHERE scope = 'platform' AND name = @name;

-- name: ActiveRegistriesOfType :many
SELECT * FROM registries WHERE is_active AND registry_type = @registry_type ORDER BY created_at DESC;

-- name: ActiveWorkspaceRegistries :many
SELECT * FROM registries
WHERE scope = 'workspace' AND is_active AND source_type <> 'managed'
ORDER BY workspace_id, name;

-- name: InsertSyncedItem :one
INSERT INTO registry_items (id, created_at, updated_at, registry_id, external_id, name, description, version, spec, tags,
    installed_entity_id, update_available, installed_version, category, sort_key, featured, recommendation_rank,
    protocol, hosting, pricing, registry_type, registry_priority, registry_active, registry_workspace_id, registry_trust)
SELECT @id, @now, @now, r.id, @external_id, @name, sqlc.narg(description), sqlc.narg(version), @spec, @tags,
    NULL, FALSE, NULL, sqlc.narg(category), @sort_key, @featured, @recommendation_rank,
    sqlc.narg(protocol), sqlc.narg(hosting), sqlc.narg(pricing),
    r.registry_type, r.recommendation_priority, r.is_active, r.workspace_id, r.trust
FROM registries r WHERE r.id = @registry_id
RETURNING *;

-- name: SetSyncedItem :exec
UPDATE registry_items SET
    name = @name, description = sqlc.narg(description), version = sqlc.narg(version), spec = @spec, tags = @tags,
    recommendation_rank = @recommendation_rank, update_available = @update_available,
    installed_entity_id = sqlc.narg(installed_entity_id), installed_version = sqlc.narg(installed_version),
    category = sqlc.narg(category), sort_key = @sort_key, featured = @featured,
    protocol = sqlc.narg(protocol), hosting = sqlc.narg(hosting), pricing = sqlc.narg(pricing),
    updated_at = @now
WHERE id = @id;

-- name: SetItemInstalled :exec
UPDATE registry_items SET installed_entity_id = sqlc.narg(installed_entity_id),
    installed_version = sqlc.narg(installed_version), updated_at = @now
WHERE id = @id;

-- name: SetItemVersion :exec
UPDATE registry_items SET version = @version, updated_at = @now WHERE id = @id;

-- MarkInSource is mark_in_source: present items are in the source, active
-- only while the registry is.
-- name: MarkInSource :exec
UPDATE registry_items ri SET in_source = p.present, registry_active = (p.present AND r.is_active)
FROM registries r, (
    SELECT i.id, i.external_id = ANY(@external_ids::text[]) AS present
    FROM registry_items i WHERE i.registry_id = @registry_id
) p
WHERE ri.id = p.id AND r.id = ri.registry_id
  AND (ri.in_source IS DISTINCT FROM p.present OR ri.registry_active IS DISTINCT FROM (p.present AND r.is_active));

-- name: CountOutOfSource :one
SELECT count(*)::int FROM registry_items WHERE registry_id = @registry_id AND NOT in_source;

-- MoveCandidates pairs each dropped item with the same item a replacement
-- registry still publishes, the first by weight.
-- name: MoveCandidates :many
SELECT DISTINCT ON (old.id) old.id AS old_id, new.id AS new_id,
       old.installed_entity_id AS old_copy, new.installed_entity_id AS new_copy
FROM registry_items old
JOIN registry_items new ON new.external_id = old.external_id AND new.registry_type = old.registry_type
WHERE old.registry_id = @registry_id AND NOT old.in_source
  AND new.registry_id = ANY(@replacements::uuid[]) AND new.in_source
ORDER BY old.id, new.registry_priority, new.registry_id;

-- name: MoveInstalls :execrows
UPDATE registry_item_installs x SET registry_item_id = m.new_id
FROM (SELECT unnest(@old_ids::uuid[]) AS old_id, unnest(@new_ids::uuid[]) AS new_id) m
WHERE x.registry_item_id = m.old_id
  AND NOT EXISTS (SELECT 1 FROM registry_item_installs other
                  WHERE other.workspace_id = x.workspace_id AND other.registry_item_id = m.new_id);

-- MoveServers moves the workspaces' servers made from a dropped item; the
-- platform's own copy stays.
-- name: MoveServers :execrows
UPDATE mcp_servers t SET registry_item_id = m.new_id
FROM (SELECT unnest(@old_ids::uuid[]) AS old_id, unnest(@new_ids::uuid[]) AS new_id, unnest(@old_copies::uuid[]) AS old_copy) m
WHERE t.registry_item_id = m.old_id AND t.id IS DISTINCT FROM m.old_copy;

-- name: ReplacedCopies :many
SELECT DISTINCT old.id, old.installed_entity_id::uuid AS copy
FROM registry_items old
JOIN registry_items new ON new.external_id = old.external_id AND new.registry_type = old.registry_type
WHERE old.registry_id = @registry_id AND NOT old.in_source AND old.installed_entity_id IS NOT NULL
  AND new.registry_id = ANY(@replacements::uuid[]) AND new.in_source AND new.installed_entity_id IS NOT NULL;

-- name: DeletePlatformServer :execrows
DELETE FROM mcp_servers WHERE id = @id AND workspace_id = 'platform';

-- name: DroppedProviderSpecs :many
SELECT ps.id FROM provider_specs ps
WHERE ps.id IN (SELECT d.installed_entity_id FROM registry_items d
                WHERE d.registry_id = @registry_id AND d.registry_type = 'llm_providers' AND NOT d.in_source)
  AND NOT EXISTS (SELECT 1 FROM registry_items live
                  WHERE live.installed_entity_id = ps.id AND live.registry_type = 'llm_providers' AND live.in_source)
FOR UPDATE;

-- LockModelSpecsOf locks the providers' models; the ids of those a
-- workspace copied (any workspace but the platform's).
-- name: LockModelSpecsOf :many
SELECT id, provider_spec_id, workspace_id FROM model_specs WHERE provider_spec_id = ANY(@ids::uuid[]) FOR UPDATE;

-- name: DroppedModelSpecs :many
SELECT ms.id FROM model_specs ms
WHERE ms.id IN (SELECT d.installed_entity_id FROM registry_items d
                WHERE d.registry_id = @registry_id AND d.registry_type = 'llm_models' AND NOT d.in_source)
  AND NOT EXISTS (SELECT 1 FROM registry_items live
                  WHERE live.installed_entity_id = ms.id AND live.registry_type = 'llm_models' AND live.in_source)
FOR UPDATE;

-- name: DeleteProviderItems :many
DELETE FROM registry_items
WHERE (registry_type = 'llm_providers' AND installed_entity_id = ANY(@ids::uuid[]))
   OR (registry_type = 'llm_models' AND installed_entity_id IN
        (SELECT id FROM model_specs WHERE provider_spec_id = ANY(@ids::uuid[])))
RETURNING registry_id;

-- name: DeleteModelItems :many
DELETE FROM registry_items WHERE registry_type = 'llm_models' AND installed_entity_id = ANY(@ids::uuid[])
RETURNING registry_id;

-- name: ClearSourceEtags :exec
UPDATE registries SET source_etag = NULL WHERE id = ANY(@ids::uuid[]);

-- name: DeleteProviderSpecs :exec
DELETE FROM provider_specs WHERE id = ANY(@ids::uuid[]);

-- name: DeleteModelSpecsByID :exec
DELETE FROM model_specs WHERE id = ANY(@ids::uuid[]);

-- OutOfSourceItems are the dropped items nothing catalog-owned holds: no
-- platform copy, no install, no server made from them.
-- name: OutOfSourceItems :many
SELECT ri.id FROM registry_items ri
WHERE ri.registry_id = @registry_id AND NOT ri.in_source AND ri.installed_entity_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM registry_item_installs x WHERE x.registry_item_id = ri.id)
  AND NOT EXISTS (SELECT 1 FROM mcp_servers s WHERE s.registry_item_id = ri.id);

-- name: DeleteItemsByID :execrows
DELETE FROM registry_items WHERE id = ANY(@ids::uuid[]);

-- name: SetOutOfSourceTrust :exec
UPDATE registry_items ri SET registry_trust = r.trust
FROM registries r
WHERE ri.registry_id = @registry_id AND r.id = ri.registry_id AND NOT ri.in_source
  AND ri.registry_trust IS DISTINCT FROM r.trust;

-- name: RecordSync :exec
UPDATE registries SET last_synced_at = @now, last_sync_error = NULL, item_count = @item_count,
    source_etag = sqlc.narg(source_etag), updated_at = @now
WHERE id = @id;

-- name: TouchSync :exec
UPDATE registries SET last_synced_at = @now, last_sync_error = NULL, updated_at = @now WHERE id = @id;

-- name: RecordSyncError :exec
UPDATE registries SET last_sync_error = @error, updated_at = @now WHERE id = @id;

-- name: InstalledItems :many
SELECT * FROM registry_items ri
WHERE ri.registry_id = @registry_id
  AND EXISTS (SELECT 1 FROM registry_item_installs x WHERE x.registry_item_id = ri.id)
ORDER BY ri.external_id;

-- UpsertProviderSpec is upsert_by_provider_key: a contract column the
-- source leaves out keeps what is stored.
-- name: UpsertProviderSpec :one
INSERT INTO provider_specs (id, provider_key, name, description, provider_type, icon, is_builtin, is_first_party,
    workspace_id, created_by, created_at, updated_at,
    base_url, transport, auth, models_path, list_shape, models_query, reasoning_param, reasoning_efforts, cache_breakpoints,
    max_image_bytes, max_image_edge, pdf_input)
VALUES (@id, @provider_key, @name, sqlc.narg(description), @provider_type, sqlc.narg(icon), @is_builtin, @is_first_party,
    'platform', 'platform', @now, @now,
    sqlc.narg(base_url), COALESCE(sqlc.narg(transport), 'openai'), COALESCE(sqlc.narg(auth), 'bearer'),
    sqlc.narg(models_path), COALESCE(sqlc.narg(list_shape), 'data_id'), sqlc.narg(models_query),
    COALESCE(sqlc.narg(reasoning_param), 'reasoning_effort'), sqlc.narg(reasoning_efforts)::jsonb,
    COALESCE(sqlc.narg(cache_breakpoints)::bool, false), sqlc.narg(max_image_bytes)::int, sqlc.narg(max_image_edge)::int,
    COALESCE(sqlc.narg(pdf_input)::bool, false))
ON CONFLICT (provider_key) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, provider_type = EXCLUDED.provider_type,
    icon = EXCLUDED.icon, is_builtin = EXCLUDED.is_builtin, is_first_party = EXCLUDED.is_first_party,
    base_url = CASE WHEN @set_base_url::bool THEN EXCLUDED.base_url ELSE provider_specs.base_url END,
    transport = CASE WHEN @set_transport::bool THEN EXCLUDED.transport ELSE provider_specs.transport END,
    auth = CASE WHEN @set_auth::bool THEN EXCLUDED.auth ELSE provider_specs.auth END,
    models_path = CASE WHEN @set_models_path::bool THEN EXCLUDED.models_path ELSE provider_specs.models_path END,
    list_shape = CASE WHEN @set_list_shape::bool THEN EXCLUDED.list_shape ELSE provider_specs.list_shape END,
    models_query = CASE WHEN @set_models_query::bool THEN EXCLUDED.models_query ELSE provider_specs.models_query END,
    reasoning_param = CASE WHEN @set_reasoning_param::bool THEN EXCLUDED.reasoning_param ELSE provider_specs.reasoning_param END,
    reasoning_efforts = CASE WHEN @set_reasoning_efforts::bool THEN EXCLUDED.reasoning_efforts ELSE provider_specs.reasoning_efforts END,
    cache_breakpoints = CASE WHEN @set_cache_breakpoints::bool THEN EXCLUDED.cache_breakpoints ELSE provider_specs.cache_breakpoints END,
    max_image_bytes = CASE WHEN @set_max_image_bytes::bool THEN EXCLUDED.max_image_bytes ELSE provider_specs.max_image_bytes END,
    max_image_edge = CASE WHEN @set_max_image_edge::bool THEN EXCLUDED.max_image_edge ELSE provider_specs.max_image_edge END,
    pdf_input = CASE WHEN @set_pdf_input::bool THEN EXCLUDED.pdf_input ELSE provider_specs.pdf_input END,
    updated_at = @now
RETURNING id;

-- name: ProviderSpecIDByKey :one
SELECT id FROM provider_specs WHERE provider_key = @provider_key;

-- UpsertPlatformModelSpec is upsert_by_provider_and_model_kwargs in the
-- platform workspace: an existing row takes the values that are not null.
-- name: UpsertPlatformModelSpec :one
INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, description, kind, context_window,
    max_output_tokens, input_cost_per_token, output_cost_per_token, cached_input_cost_per_token,
    cache_creation_input_cost_per_token, supports_function_calling, supports_vision, supports_reasoning,
    reasoning_efforts, responses_lite, is_active, workspace_id, created_by, created_at, updated_at)
VALUES (@id, @provider_spec_id, @model_name, @display_name, sqlc.narg(description), @kind, sqlc.narg(context_window),
    sqlc.narg(max_output_tokens), sqlc.narg(input_cost)::numeric, sqlc.narg(output_cost)::numeric,
    sqlc.narg(cached_input_cost)::numeric, sqlc.narg(cache_creation_cost)::numeric,
    @supports_function_calling, @supports_vision, @supports_reasoning, sqlc.narg(reasoning_efforts)::jsonb,
    @responses_lite, @is_active, 'platform', 'platform', @now, @now)
ON CONFLICT (workspace_id, provider_spec_id, model_name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = COALESCE(EXCLUDED.description, model_specs.description),
    kind = EXCLUDED.kind,
    context_window = COALESCE(EXCLUDED.context_window, model_specs.context_window),
    max_output_tokens = COALESCE(EXCLUDED.max_output_tokens, model_specs.max_output_tokens),
    input_cost_per_token = COALESCE(EXCLUDED.input_cost_per_token, model_specs.input_cost_per_token),
    output_cost_per_token = COALESCE(EXCLUDED.output_cost_per_token, model_specs.output_cost_per_token),
    cached_input_cost_per_token = COALESCE(EXCLUDED.cached_input_cost_per_token, model_specs.cached_input_cost_per_token),
    cache_creation_input_cost_per_token = COALESCE(EXCLUDED.cache_creation_input_cost_per_token, model_specs.cache_creation_input_cost_per_token),
    supports_function_calling = EXCLUDED.supports_function_calling,
    supports_vision = EXCLUDED.supports_vision,
    supports_reasoning = EXCLUDED.supports_reasoning,
    reasoning_efforts = COALESCE(EXCLUDED.reasoning_efforts, model_specs.reasoning_efforts),
    responses_lite = EXCLUDED.responses_lite,
    is_active = EXCLUDED.is_active,
    updated_at = @now
RETURNING id;

-- name: ResyncCachedInputPrice :execrows
UPDATE model_specs SET cached_input_cost_per_token = @price::numeric
WHERE provider_spec_id = @provider_spec_id AND model_name = @model_name
  AND (cached_input_cost_per_token IS NULL OR (@has_old::bool AND cached_input_cost_per_token = @old::numeric))
  AND cached_input_cost_per_token IS DISTINCT FROM @price::numeric;

-- name: ResyncCacheCreationPrice :execrows
UPDATE model_specs SET cache_creation_input_cost_per_token = @price::numeric
WHERE provider_spec_id = @provider_spec_id AND model_name = @model_name
  AND (cache_creation_input_cost_per_token IS NULL OR (@has_old::bool AND cache_creation_input_cost_per_token = @old::numeric))
  AND cache_creation_input_cost_per_token IS DISTINCT FROM @price::numeric;

-- name: BackfillMirroredServer :exec
UPDATE mcp_servers SET json_spec = @json_spec::jsonb, remote_url = sqlc.narg(remote_url),
    registry_url = sqlc.narg(registry_url), env_schema = @env_schema::json
WHERE id = @id AND workspace_id = 'platform';
