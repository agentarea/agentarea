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
