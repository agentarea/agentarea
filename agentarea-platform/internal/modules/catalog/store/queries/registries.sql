-- name: GetRegistry :one
SELECT * FROM registries WHERE id = @id;

-- name: RegistriesByIDs :many
SELECT * FROM registries WHERE id = ANY(@ids::uuid[]);

-- ListVisibleRegistries is list_visible: the platform's and the workspace's.
-- name: ListVisibleRegistries :many
SELECT * FROM registries
WHERE (workspace_id IS NULL OR workspace_id = @workspace_id)
  AND (NOT @active_only::bool OR is_active)
  AND (@registry_type::text = '' OR registry_type = @registry_type::text)
  AND (@scope::text = '' OR scope = @scope::text)
ORDER BY created_at DESC;

-- name: CreateRegistry :one
INSERT INTO registries (id, created_at, updated_at, name, description, registry_type, source_type, source_url,
    is_active, last_synced_at, last_sync_error, source_etag, item_count, recommendation_priority, scope,
    workspace_id, mode, trust, credentials_secret_ref, source_ref, source_path)
VALUES (@id, @now, @now, @name, sqlc.narg(description), @registry_type, @source_type, @source_url,
    TRUE, NULL, NULL, NULL, 0, @recommendation_priority, @scope,
    sqlc.narg(workspace_id), @mode, @trust, sqlc.narg(credentials_secret_ref), sqlc.narg(source_ref), sqlc.narg(source_path))
RETURNING *;

-- UpdateRegistry writes the fields set; updated_at moves only when a value changes.
-- name: UpdateRegistry :one
UPDATE registries SET
    name = CASE WHEN @set_name::bool THEN @name::varchar ELSE name END,
    description = CASE WHEN @set_description::bool THEN sqlc.narg(description)::text ELSE description END,
    source_url = CASE WHEN @set_source_url::bool THEN @source_url::text ELSE source_url END,
    source_type = CASE WHEN @set_source_type::bool THEN @source_type::varchar ELSE source_type END,
    is_active = CASE WHEN @set_is_active::bool THEN @is_active::bool ELSE is_active END,
    recommendation_priority = CASE WHEN @set_priority::bool THEN @recommendation_priority::int ELSE recommendation_priority END,
    mode = CASE WHEN @set_mode::bool THEN @mode::varchar ELSE mode END,
    trust = CASE WHEN @set_trust::bool THEN @trust::varchar ELSE trust END,
    credentials_secret_ref = CASE WHEN @set_credentials::bool THEN sqlc.narg(credentials_secret_ref)::uuid ELSE credentials_secret_ref END,
    source_ref = CASE WHEN @set_source_ref::bool THEN sqlc.narg(source_ref)::varchar ELSE source_ref END,
    source_path = CASE WHEN @set_source_path::bool THEN sqlc.narg(source_path)::text ELSE source_path END,
    source_etag = CASE WHEN @clear_etag::bool THEN NULL ELSE source_etag END,
    updated_at = CASE WHEN
        (@set_name AND name IS DISTINCT FROM @name::varchar)
        OR (@set_description AND description IS DISTINCT FROM sqlc.narg(description)::text)
        OR (@set_source_url AND source_url IS DISTINCT FROM @source_url::text)
        OR (@set_source_type AND source_type IS DISTINCT FROM @source_type::varchar)
        OR (@set_is_active AND is_active IS DISTINCT FROM @is_active::bool)
        OR (@set_priority AND recommendation_priority IS DISTINCT FROM @recommendation_priority::int)
        OR (@set_mode AND mode IS DISTINCT FROM @mode::varchar)
        OR (@set_trust AND trust IS DISTINCT FROM @trust::varchar)
        OR (@set_credentials AND credentials_secret_ref IS DISTINCT FROM sqlc.narg(credentials_secret_ref)::uuid)
        OR (@set_source_ref AND source_ref IS DISTINCT FROM sqlc.narg(source_ref)::varchar)
        OR (@set_source_path AND source_path IS DISTINCT FROM sqlc.narg(source_path)::text)
        OR (@clear_etag AND source_etag IS NOT NULL)
        THEN @now ELSE updated_at END
WHERE id = @id
RETURNING *;

-- CopyRegistryToItems is RegistryRepository.update's copy of the registry's
-- type, weight, active flag, workspace and trust onto its items.
-- name: CopyRegistryToItems :exec
UPDATE registry_items SET
    registry_priority = CASE WHEN @set_priority::bool THEN @registry_priority::int ELSE registry_priority END,
    registry_active = CASE WHEN @set_active::bool THEN (@registry_active::bool AND in_source) ELSE registry_active END,
    registry_trust = CASE WHEN @set_trust::bool THEN @registry_trust::varchar ELSE registry_trust END,
    updated_at = @now
WHERE registry_id = @registry_id;

-- name: SetRegistryItemCount :exec
UPDATE registries SET item_count = @item_count,
    updated_at = CASE WHEN item_count IS DISTINCT FROM @item_count THEN @now ELSE updated_at END
WHERE id = @id;

-- name: DeleteRegistry :execrows
DELETE FROM registries WHERE id = @id;
