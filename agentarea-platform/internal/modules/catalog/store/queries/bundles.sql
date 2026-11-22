-- name: GetInstalledBundle :one
SELECT * FROM installed_bundles WHERE workspace_id = @workspace_id AND id = @id;

-- name: ListInstalledBundlesByName :many
SELECT * FROM installed_bundles WHERE workspace_id = @workspace_id AND name = @name
ORDER BY created_at, id;

-- name: ListInstalledBundleResults :many
SELECT id, name, install_result FROM installed_bundles WHERE workspace_id = @workspace_id
ORDER BY created_at, id;

-- name: InsertInstalledBundle :one
INSERT INTO installed_bundles (id, created_at, updated_at, workspace_id, created_by, updated_by, name, display_name, description,
    schema_version, status, canonical, install_result, source)
VALUES (@id, @now, @now, @workspace_id, @created_by, @created_by, @name, sqlc.narg(display_name), @description,
    @schema_version, @status, @canonical::jsonb, @install_result::jsonb, sqlc.narg(source)::jsonb)
RETURNING id;

-- name: UpdateInstalledBundle :execrows
UPDATE installed_bundles SET name = @name, display_name = sqlc.narg(display_name), description = @description,
    schema_version = @schema_version, status = @status, canonical = @canonical::jsonb,
    install_result = @install_result::jsonb, updated_at = @now, updated_by = @updated_by,
    source = COALESCE(sqlc.narg(source)::jsonb, source)
WHERE id = @id AND workspace_id = @workspace_id AND updated_at = @seen_updated_at;

-- name: CatalogMCPItemByExternalID :one
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, ri.created_at, ri.updated_at FROM registry_items ri
WHERE ri.registry_type = 'mcp_servers' AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND ri.external_id = @external_id
ORDER BY ri.sort_key, ri.id
LIMIT 1;
