-- MCP server specs as connections reads and writes them (MCPServerRepository).

-- name: GetWorkspaceMCPSpec :one
SELECT * FROM mcp_servers WHERE id = @id AND workspace_id = @workspace_id;

-- GetCatalogMirrorMCPSpec is a platform mirror of an item of an active registry.
-- name: GetCatalogMirrorMCPSpec :one
SELECT s.* FROM mcp_servers s
WHERE s.id = @id AND s.workspace_id = 'platform'
  AND EXISTS (SELECT 1 FROM registry_items ri JOIN registries r ON r.id = ri.registry_id
              WHERE ri.id = s.registry_item_id AND r.is_active);

-- name: GetPlatformMCPSpec :one
SELECT * FROM mcp_servers WHERE id = @id AND workspace_id = 'platform';

-- CatalogMCPItem is CatalogMcpRepository.get_item: an mcp_servers item of an active registry.
-- name: CatalogMCPItem :one
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, ri.created_at, ri.updated_at
FROM registry_items ri JOIN registries r ON r.id = ri.registry_id
WHERE r.registry_type = 'mcp_servers' AND r.is_active AND ri.id = @id;

-- name: MCPSpecSlugTaken :one
SELECT EXISTS (SELECT 1 FROM mcp_servers WHERE workspace_id = @workspace_id AND slug = @slug)::bool;

-- name: InsertMCPSpec :one
INSERT INTO mcp_servers (
    id, name, slug, description, docker_image_url, version, tags, status, is_public,
    env_schema, cmd, remote_url, registry_item_id, json_spec, registry_url, icon,
    workspace_id, created_by, created_at, updated_at
) VALUES (
    @id, @name, @slug, @description, sqlc.narg(docker_image_url), @version, @tags::json, @status, @is_public,
    @env_schema::json, sqlc.narg(cmd)::json, sqlc.narg(remote_url), sqlc.narg(registry_item_id),
    sqlc.narg(json_spec)::jsonb, sqlc.narg(registry_url), sqlc.narg(icon),
    @workspace_id, @created_by, @now, @now
)
RETURNING *;

-- name: SetMCPSpecJSONSpec :execrows
UPDATE mcp_servers SET json_spec = @json_spec::jsonb
WHERE id = @id AND workspace_id = @workspace_id;

-- The tenant half of list_servers (_build_list_query): the workspace's rows
-- the caller may read, without specs of a deactivated registry. A NULL
-- filter is no filter; readable is always applied.

-- name: CountTenantMCPSpecs :one
SELECT count(*) FROM mcp_servers s
WHERE s.workspace_id = @workspace_id AND s.id = ANY(@readable::uuid[])
  AND (sqlc.narg(spec_ids)::uuid[] IS NULL OR s.id = ANY(sqlc.narg(spec_ids)::uuid[]))
  AND (sqlc.narg(status)::text IS NULL OR s.status = sqlc.narg(status)::text)
  AND (sqlc.narg(is_public)::bool IS NULL OR s.is_public = sqlc.narg(is_public)::bool)
  AND (sqlc.narg(tag_pattern)::text IS NULL OR s.tags::text ILIKE sqlc.narg(tag_pattern)::text)
  AND (sqlc.narg(search)::text IS NULL OR s.name ILIKE sqlc.narg(search)::text OR s.description ILIKE sqlc.narg(search)::text)
  AND (s.registry_item_id IS NULL OR EXISTS (SELECT 1 FROM registry_items ri JOIN registries r ON r.id = ri.registry_id
                                             WHERE ri.id = s.registry_item_id AND r.is_active));

-- name: ListTenantMCPSpecs :many
SELECT s.* FROM mcp_servers s
WHERE s.workspace_id = @workspace_id AND s.id = ANY(@readable::uuid[])
  AND (sqlc.narg(spec_ids)::uuid[] IS NULL OR s.id = ANY(sqlc.narg(spec_ids)::uuid[]))
  AND (sqlc.narg(status)::text IS NULL OR s.status = sqlc.narg(status)::text)
  AND (sqlc.narg(is_public)::bool IS NULL OR s.is_public = sqlc.narg(is_public)::bool)
  AND (sqlc.narg(tag_pattern)::text IS NULL OR s.tags::text ILIKE sqlc.narg(tag_pattern)::text)
  AND (sqlc.narg(search)::text IS NULL OR s.name ILIKE sqlc.narg(search)::text OR s.description ILIKE sqlc.narg(search)::text)
  AND (s.registry_item_id IS NULL OR EXISTS (SELECT 1 FROM registry_items ri JOIN registries r ON r.id = ri.registry_id
                                             WHERE ri.id = s.registry_item_id AND r.is_active))
ORDER BY CASE WHEN s.json_spec::text LIKE '%"icons"%' THEN 0 ELSE 1 END, s.name, s.id
LIMIT @lim OFFSET @off;

-- name: InstantiatedMCPItems :many
SELECT DISTINCT s.registry_item_id::uuid FROM mcp_servers s
WHERE s.workspace_id = @workspace_id AND s.id = ANY(@readable::uuid[]) AND s.registry_item_id IS NOT NULL
  AND (sqlc.narg(spec_ids)::uuid[] IS NULL OR s.id = ANY(sqlc.narg(spec_ids)::uuid[]))
  AND (sqlc.narg(status)::text IS NULL OR s.status = sqlc.narg(status)::text)
  AND (sqlc.narg(is_public)::bool IS NULL OR s.is_public = sqlc.narg(is_public)::bool)
  AND (sqlc.narg(tag_pattern)::text IS NULL OR s.tags::text ILIKE sqlc.narg(tag_pattern)::text)
  AND (sqlc.narg(search)::text IS NULL OR s.name ILIKE sqlc.narg(search)::text OR s.description ILIKE sqlc.narg(search)::text)
  AND EXISTS (SELECT 1 FROM registry_items ri JOIN registries r ON r.id = ri.registry_id
              WHERE ri.id = s.registry_item_id AND r.is_active);

-- The catalog half of list_servers (CatalogMcpRepository.list_page): the
-- items of active mcp_servers registries the workspace sees, none a tenant
-- spec already instantiates.

-- name: CountCatalogMCPItems :one
SELECT count(*) FROM registry_items ri
WHERE ri.registry_type = 'mcp_servers' AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND NOT (ri.id = ANY(@exclude::uuid[]))
  AND (sqlc.narg(item_ids)::uuid[] IS NULL OR ri.id = ANY(sqlc.narg(item_ids)::uuid[]))
  AND (sqlc.narg(tag)::jsonb IS NULL OR ri.tags @> sqlc.narg(tag)::jsonb)
  AND (sqlc.narg(search)::text IS NULL OR ri.name ILIKE sqlc.narg(search)::text OR COALESCE(ri.description, '') ILIKE sqlc.narg(search)::text);

-- name: ListCatalogMCPItems :many
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, ri.created_at, ri.updated_at FROM registry_items ri
WHERE ri.registry_type = 'mcp_servers' AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND NOT (ri.id = ANY(@exclude::uuid[]))
  AND (sqlc.narg(item_ids)::uuid[] IS NULL OR ri.id = ANY(sqlc.narg(item_ids)::uuid[]))
  AND (sqlc.narg(tag)::jsonb IS NULL OR ri.tags @> sqlc.narg(tag)::jsonb)
  AND (sqlc.narg(search)::text IS NULL OR ri.name ILIKE sqlc.narg(search)::text OR COALESCE(ri.description, '') ILIKE sqlc.narg(search)::text)
ORDER BY ri.sort_key, ri.id
LIMIT @lim OFFSET @off;

-- name: GetWorkspaceMCPSpecBySlug :one
SELECT * FROM mcp_servers WHERE workspace_id = @workspace_id AND slug = @slug;

-- name: UpdateMCPSpec :one
UPDATE mcp_servers SET
    name = @name, description = @description, docker_image_url = sqlc.narg(docker_image_url),
    remote_url = sqlc.narg(remote_url), version = @version, tags = @tags::json, is_public = @is_public,
    status = @status, env_schema = @env_schema::json, cmd = sqlc.narg(cmd)::json,
    json_spec = sqlc.narg(json_spec)::jsonb, registry_url = sqlc.narg(registry_url),
    updated_by = @updated_by, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id
RETURNING *;

-- name: DeleteMCPSpec :execrows
DELETE FROM mcp_servers WHERE id = @id AND workspace_id = @workspace_id;
