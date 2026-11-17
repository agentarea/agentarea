-- name: GetItem :one
SELECT * FROM registry_items WHERE id = @id;

-- name: GetItemByExternalID :one
SELECT * FROM registry_items WHERE registry_id = @registry_id AND external_id = @external_id;

-- name: ListRegistryItems :many
SELECT * FROM registry_items WHERE registry_id = @registry_id
ORDER BY lower(name) LIMIT @lim OFFSET @off;

-- name: CountRegistryItems :one
SELECT count(*) FROM registry_items WHERE registry_id = @registry_id;

-- name: NextRecommendationRank :one
SELECT COALESCE(max(recommendation_rank) + 1, 0)::int FROM registry_items WHERE registry_id = @registry_id;

-- name: CreateItem :one
INSERT INTO registry_items (id, created_at, updated_at, registry_id, external_id, name, description, version, spec, tags,
    installed_entity_id, update_available, installed_version, category, sort_key, featured, recommendation_rank,
    protocol, hosting, pricing, registry_type, registry_priority, registry_active, registry_workspace_id, registry_trust)
SELECT @id, @now, @now, r.id, @external_id, @name, sqlc.narg(description), sqlc.narg(version), @spec, @tags,
    NULL, FALSE, NULL, sqlc.narg(category), @sort_key, @featured, @recommendation_rank,
    sqlc.narg(protocol), sqlc.narg(hosting), sqlc.narg(pricing),
    r.registry_type, r.recommendation_priority, r.is_active, r.workspace_id, r.trust
FROM registries r WHERE r.id = @registry_id
RETURNING *;

-- UpdateItem writes the fields set and the derived facets.
-- name: UpdateItem :one
UPDATE registry_items SET
    external_id = CASE WHEN @set_external_id::bool THEN @external_id::varchar ELSE external_id END,
    name = CASE WHEN @set_name::bool THEN @name::varchar ELSE name END,
    description = CASE WHEN @set_description::bool THEN sqlc.narg(description)::text ELSE description END,
    version = CASE WHEN @set_version::bool THEN sqlc.narg(version)::varchar ELSE version END,
    spec = CASE WHEN @set_spec::bool THEN @spec::jsonb ELSE spec END,
    tags = CASE WHEN @set_tags::bool THEN @tags::jsonb ELSE tags END,
    category = sqlc.narg(category)::varchar,
    sort_key = @sort_key::varchar,
    featured = @featured::bool,
    protocol = sqlc.narg(protocol)::varchar,
    hosting = sqlc.narg(hosting)::varchar,
    pricing = sqlc.narg(pricing)::varchar,
    updated_at = @now
WHERE id = @id
RETURNING *;

-- name: DeleteItem :execrows
DELETE FROM registry_items WHERE id = @id;

-- SearchItems is RegistryItemRepository.search: no active or in-source filter.
-- name: SearchItems :many
SELECT * FROM registry_items
WHERE (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id)
  AND registry_active
  AND (@tag::text = '' OR tags::jsonb @> jsonb_build_array(@tag::text))
  AND (NOT @filter_update::bool OR update_available = @update_available::bool)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text OR external_id ILIKE @pattern::text)
ORDER BY name
LIMIT @lim OFFSET @off;

-- name: AllRegistryItems :many
SELECT * FROM registry_items WHERE registry_id = @registry_id ORDER BY lower(name);

-- MarkItemApplied is update_item_spec's bookkeeping.
-- name: MarkItemApplied :exec
UPDATE registry_items SET update_available = FALSE, installed_version = @installed_version, updated_at = @now
WHERE id = @id;
