-- name: ProviderSpecByID :one
SELECT id, provider_key, provider_type, name, description, icon, is_builtin, is_first_party, requires_api_key,
    base_url, transport, auth, models_path, list_shape, models_query, reasoning_param, reasoning_efforts,
    cache_breakpoints, max_image_bytes, max_image_edge, pdf_input, workspace_id, created_by, created_at, updated_at
FROM provider_specs WHERE id = @id;

-- name: ProviderSpecByKey :one
SELECT id, provider_key, provider_type, name, description, icon, is_builtin, is_first_party, requires_api_key,
    base_url, transport, auth, models_path, list_shape, models_query, reasoning_param, reasoning_efforts,
    cache_breakpoints, max_image_bytes, max_image_edge, pdf_input, workspace_id, created_by, created_at, updated_at
FROM provider_specs WHERE provider_key = @provider_key;

-- name: ProviderSpecsByIDs :many
SELECT id, provider_key, provider_type, name, description, icon, is_builtin, is_first_party, requires_api_key,
    base_url, transport, auth, models_path, list_shape, models_query, reasoning_param, reasoning_efforts,
    cache_breakpoints, max_image_bytes, max_image_edge, pdf_input, workspace_id, created_by, created_at, updated_at
FROM provider_specs WHERE id = ANY(@ids::uuid[]);

-- name: ModelSpecsByIDs :many
SELECT id, provider_spec_id, workspace_id, created_by, model_name, display_name, description, kind,
    context_window, max_output_tokens,
    input_cost_per_token AS input_cost,
    output_cost_per_token AS output_cost,
    cached_input_cost_per_token AS cached_input_cost,
    cache_creation_input_cost_per_token AS cache_creation_input_cost,
    output_cost_per_image AS image_cost,
    output_cost_per_video_per_second AS video_cost,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, responses_lite,
    default_context_strategy, is_active, created_at, updated_at
FROM model_specs WHERE id = ANY(@ids::uuid[]);

-- UsableModelSpec is get_usable: the workspace's own spec or the platform's.
-- name: UsableModelSpec :one
SELECT id, provider_spec_id, workspace_id, created_by, model_name, display_name, description, kind,
    context_window, max_output_tokens,
    input_cost_per_token AS input_cost,
    output_cost_per_token AS output_cost,
    cached_input_cost_per_token AS cached_input_cost,
    cache_creation_input_cost_per_token AS cache_creation_input_cost,
    output_cost_per_image AS image_cost,
    output_cost_per_video_per_second AS video_cost,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, responses_lite,
    default_context_strategy, is_active, created_at, updated_at
FROM model_specs WHERE id = @id AND (workspace_id = @workspace_id OR workspace_id = 'platform');

-- ModelSpecByProviderAndName is find_one_by in the workspace: newest first.
-- name: ModelSpecByProviderAndName :one
SELECT id, provider_spec_id, workspace_id, created_by, model_name, display_name, description, kind,
    context_window, max_output_tokens,
    input_cost_per_token AS input_cost,
    output_cost_per_token AS output_cost,
    cached_input_cost_per_token AS cached_input_cost,
    cache_creation_input_cost_per_token AS cache_creation_input_cost,
    output_cost_per_image AS image_cost,
    output_cost_per_video_per_second AS video_cost,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, responses_lite,
    default_context_strategy, is_active, created_at, updated_at
FROM model_specs WHERE workspace_id = @workspace_id AND provider_spec_id = @provider_spec_id AND model_name = @model_name
ORDER BY created_at DESC LIMIT 1;

-- name: ModelSpecIDsByNames :many
SELECT model_name, id FROM model_specs
WHERE workspace_id = @workspace_id AND provider_spec_id = @provider_spec_id AND model_name = ANY(@names::text[]);

-- name: InsertModelSpec :exec
INSERT INTO model_specs (id, created_at, updated_at, workspace_id, created_by, provider_spec_id, model_name,
    display_name, description, kind, context_window, max_output_tokens, input_cost_per_token,
    output_cost_per_token, cached_input_cost_per_token, cache_creation_input_cost_per_token,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, is_active)
VALUES (@id, @now, @now, @workspace_id, @created_by, @provider_spec_id, @model_name,
    @display_name, sqlc.narg(description), @kind, sqlc.narg(context_window), sqlc.narg(max_output_tokens),
    sqlc.narg(input_cost)::text::numeric, sqlc.narg(output_cost)::text::numeric, sqlc.narg(cached_input_cost)::text::numeric,
    sqlc.narg(cache_creation_input_cost)::text::numeric,
    sqlc.narg(supports_function_calling), sqlc.narg(supports_vision), sqlc.narg(supports_reasoning),
    sqlc.narg(reasoning_efforts), @is_active);

-- InsertModelSpecIfAbsent is the catalog copy: a racing first add is a no-op.
-- name: InsertModelSpecIfAbsent :exec
INSERT INTO model_specs (id, created_at, updated_at, workspace_id, created_by, provider_spec_id, model_name,
    display_name, description, kind, context_window, max_output_tokens, input_cost_per_token,
    output_cost_per_token, cached_input_cost_per_token, cache_creation_input_cost_per_token,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, is_active)
VALUES (@id, @now, @now, @workspace_id, @created_by, @provider_spec_id, @model_name,
    @display_name, sqlc.narg(description), @kind, sqlc.narg(context_window), sqlc.narg(max_output_tokens),
    sqlc.narg(input_cost)::text::numeric, sqlc.narg(output_cost)::text::numeric, sqlc.narg(cached_input_cost)::text::numeric,
    sqlc.narg(cache_creation_input_cost)::text::numeric,
    sqlc.narg(supports_function_calling), sqlc.narg(supports_vision), sqlc.narg(supports_reasoning),
    sqlc.narg(reasoning_efforts), @is_active)
ON CONFLICT ON CONSTRAINT uq_model_specs_workspace_provider_model DO NOTHING;

-- UpdateDiscoveredSpec writes the fields that are not null.
-- name: UpdateDiscoveredSpec :exec
UPDATE model_specs SET
    display_name = COALESCE(sqlc.narg(display_name), display_name),
    description = COALESCE(sqlc.narg(description), description),
    kind = COALESCE(sqlc.narg(kind), kind),
    context_window = COALESCE(sqlc.narg(context_window), context_window),
    max_output_tokens = COALESCE(sqlc.narg(max_output_tokens), max_output_tokens),
    input_cost_per_token = COALESCE(sqlc.narg(input_cost)::text::numeric, input_cost_per_token),
    output_cost_per_token = COALESCE(sqlc.narg(output_cost)::text::numeric, output_cost_per_token),
    cached_input_cost_per_token = COALESCE(sqlc.narg(cached_input_cost)::text::numeric, cached_input_cost_per_token),
    cache_creation_input_cost_per_token = COALESCE(sqlc.narg(cache_creation_input_cost)::text::numeric, cache_creation_input_cost_per_token),
    supports_function_calling = COALESCE(sqlc.narg(supports_function_calling), supports_function_calling),
    supports_vision = COALESCE(sqlc.narg(supports_vision), supports_vision),
    supports_reasoning = COALESCE(sqlc.narg(supports_reasoning), supports_reasoning),
    updated_at = @now
WHERE id = @id;

-- CatalogModelItems is catalog_model_spec_repository.list_items: items of
-- active llm_models registries, preferred registry first.
-- name: CatalogModelItems :many
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.created_at, ri.updated_at,
    ps.id AS provider_spec_id, ps.provider_key, ps.name AS provider_name
FROM registry_items ri
JOIN registries r ON r.id = ri.registry_id
LEFT JOIN provider_specs ps ON ps.provider_key = ri.spec->>'provider_key'
WHERE r.registry_type = 'llm_models' AND ri.registry_active
ORDER BY ri.registry_priority, ri.id;

-- name: CatalogModelItem :one
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.created_at, ri.updated_at,
    ps.id AS provider_spec_id, ps.provider_key, ps.name AS provider_name
FROM registry_items ri
JOIN registries r ON r.id = ri.registry_id
LEFT JOIN provider_specs ps ON ps.provider_key = ri.spec->>'provider_key'
WHERE r.registry_type = 'llm_models' AND ri.registry_active AND ri.id = @id;

-- OfferedProviderSpecs is ProviderSpecRepository.list_specs: offered_to the
-- workspace, its configs' and instances' specs given by models.
-- name: OfferedProviderSpecs :many
SELECT id, provider_key, provider_type, name, description, icon, is_builtin, is_first_party, requires_api_key,
    base_url, transport, auth, models_path, list_shape, models_query, reasoning_param, reasoning_efforts,
    cache_breakpoints, max_image_bytes, max_image_edge, pdf_input, workspace_id, created_by, created_at, updated_at
FROM provider_specs ps
WHERE (NOT EXISTS (SELECT 1 FROM registry_items ri WHERE ri.installed_entity_id = ps.id AND ri.registry_type = 'llm_providers')
    OR EXISTS (SELECT 1 FROM registry_items ri WHERE ri.installed_entity_id = ps.id AND ri.registry_type = 'llm_providers' AND ri.in_source IS TRUE)
    OR ps.id = ANY(@config_providers::uuid[])
    OR EXISTS (SELECT 1 FROM model_specs ms WHERE ms.provider_spec_id = ps.id
        AND (ms.workspace_id = @workspace_id OR ms.id = ANY(@instance_specs::uuid[]))))
  AND (sqlc.narg(is_builtin)::bool IS NULL OR ps.is_builtin = sqlc.narg(is_builtin)::bool)
ORDER BY ps.is_first_party DESC, lower(ps.name)
LIMIT 100;

-- ModelSpecsOfProviders is the ProviderSpec.model_specs relationship: every
-- workspace's rows.
-- name: ModelSpecsOfProviders :many
SELECT id, provider_spec_id, workspace_id, created_by, model_name, display_name, description, kind,
    context_window, max_output_tokens,
    input_cost_per_token AS input_cost,
    output_cost_per_token AS output_cost,
    cached_input_cost_per_token AS cached_input_cost,
    cache_creation_input_cost_per_token AS cache_creation_input_cost,
    output_cost_per_image AS image_cost,
    output_cost_per_video_per_second AS video_cost,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, responses_lite,
    default_context_strategy, is_active, created_at, updated_at
FROM model_specs WHERE provider_spec_id = ANY(@ids::uuid[]) AND workspace_id = @workspace_id
ORDER BY created_at, id;

-- OwnModelSpecs is list_all on model_specs: the workspace's rows, newest first.
-- name: OwnModelSpecs :many
SELECT id, provider_spec_id, workspace_id, created_by, model_name, display_name, description, kind,
    context_window, max_output_tokens,
    input_cost_per_token AS input_cost,
    output_cost_per_token AS output_cost,
    cached_input_cost_per_token AS cached_input_cost,
    cache_creation_input_cost_per_token AS cache_creation_input_cost,
    output_cost_per_image AS image_cost,
    output_cost_per_video_per_second AS video_cost,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, responses_lite,
    default_context_strategy, is_active, created_at, updated_at
FROM model_specs
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(provider_spec_id)::uuid IS NULL OR provider_spec_id = sqlc.narg(provider_spec_id)::uuid)
  AND (sqlc.narg(is_active)::bool IS NULL OR is_active = sqlc.narg(is_active)::bool)
  AND (sqlc.narg(kind)::text IS NULL OR kind = sqlc.narg(kind)::text)
ORDER BY created_at DESC;

-- name: OwnModelSpec :one
SELECT id, provider_spec_id, workspace_id, created_by, model_name, display_name, description, kind,
    context_window, max_output_tokens,
    input_cost_per_token AS input_cost,
    output_cost_per_token AS output_cost,
    cached_input_cost_per_token AS cached_input_cost,
    cache_creation_input_cost_per_token AS cache_creation_input_cost,
    output_cost_per_image AS image_cost,
    output_cost_per_video_per_second AS video_cost,
    supports_function_calling, supports_vision, supports_reasoning, reasoning_efforts, responses_lite,
    default_context_strategy, is_active, created_at, updated_at
FROM model_specs WHERE id = @id AND workspace_id = @workspace_id;

-- name: OwnModelKeys :many
SELECT provider_spec_id, model_name FROM model_specs WHERE workspace_id = @workspace_id;

-- CreateModelSpec is ModelSpecRepository.create from the API body.
-- name: CreateModelSpec :exec
INSERT INTO model_specs (id, created_at, updated_at, workspace_id, created_by, provider_spec_id, model_name,
    display_name, description, kind, context_window, max_output_tokens, input_cost_per_token,
    output_cost_per_token, cached_input_cost_per_token, cache_creation_input_cost_per_token,
    supports_function_calling, supports_vision, supports_reasoning, default_context_strategy, is_active)
VALUES (@id, @now, @now, @workspace_id, @created_by, @provider_spec_id, @model_name,
    @display_name, sqlc.narg(description), @kind, sqlc.narg(context_window), sqlc.narg(max_output_tokens),
    sqlc.narg(input_cost)::text::numeric, sqlc.narg(output_cost)::text::numeric, sqlc.narg(cached_input_cost)::text::numeric,
    sqlc.narg(cache_creation_input_cost)::text::numeric, FALSE, FALSE, FALSE,
    sqlc.narg(default_context_strategy), @is_active);

-- UpdateModelSpec writes the fields that are not null; updated_at moves
-- only when touch (a value changed).
-- name: UpdateModelSpec :execrows
UPDATE model_specs SET
    display_name = COALESCE(sqlc.narg(display_name), display_name),
    description = COALESCE(sqlc.narg(description), description),
    kind = COALESCE(sqlc.narg(kind), kind),
    context_window = COALESCE(sqlc.narg(context_window), context_window),
    max_output_tokens = COALESCE(sqlc.narg(max_output_tokens), max_output_tokens),
    input_cost_per_token = COALESCE(sqlc.narg(input_cost)::text::numeric, input_cost_per_token),
    output_cost_per_token = COALESCE(sqlc.narg(output_cost)::text::numeric, output_cost_per_token),
    cached_input_cost_per_token = COALESCE(sqlc.narg(cached_input_cost)::text::numeric, cached_input_cost_per_token),
    cache_creation_input_cost_per_token = COALESCE(sqlc.narg(cache_creation_input_cost)::text::numeric, cache_creation_input_cost_per_token),
    default_context_strategy = COALESCE(sqlc.narg(default_context_strategy), default_context_strategy),
    is_active = COALESCE(sqlc.narg(is_active), is_active),
    updated_at = CASE WHEN @touch::bool THEN @now ELSE updated_at END
WHERE id = @id AND workspace_id = @workspace_id;

-- name: DeleteOwnModelSpec :execrows
DELETE FROM model_specs WHERE id = @id AND workspace_id = @workspace_id;
