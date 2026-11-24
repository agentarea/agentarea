-- name: SkillInsertFromCatalog :exec
INSERT INTO skills (id, name, slug, description, source_type, source_url, content, s3_path, network_scope,
                    registry_item_id, workspace_id, created_by, created_at, updated_at)
VALUES (@id, @name, @slug, sqlc.narg(description)::text, @source_type, sqlc.narg(source_url)::varchar, NULL,
        @s3_path, @network_scope, @registry_item_id, @workspace_id, @created_by, @now, @now);

-- name: SkillGetByRegistryItem :one
SELECT id, name, slug, description, source_type, source_url, network_scope, workspace_id, created_by,
       created_at, updated_at, registry_item_id, s3_path
FROM skills WHERE workspace_id = @workspace_id AND registry_item_id = @registry_item_id
ORDER BY created_at, id LIMIT 1;

-- name: SkillsFromCatalog :many
SELECT id, name, slug, description, source_type, source_url, network_scope, workspace_id, created_by,
       created_at, updated_at, registry_item_id, s3_path, content
FROM skills WHERE workspace_id = @workspace_id AND registry_item_id IS NOT NULL
ORDER BY name, id;

-- name: SkillSetSource :exec
UPDATE skills SET source_url = sqlc.narg(source_url)::varchar, source_type = @source_type,
    registry_item_id = sqlc.narg(registry_item_id)::uuid,
    description = COALESCE(sqlc.narg(description)::text, description), updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: SkillsInstalledFromCatalog :many
SELECT id, workspace_id FROM skills
WHERE registry_item_id IS NOT NULL AND workspace_id <> @platform_workspace_id
ORDER BY workspace_id, id;

-- name: SkillsOutsidePlatform :many
SELECT id, workspace_id FROM skills WHERE workspace_id <> @platform_workspace_id
ORDER BY workspace_id, id;
