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
    @id, @name, @slug, @description, sqlc.narg(docker_image_url), @version, @tags::json, @status, false,
    @env_schema::json, sqlc.narg(cmd)::json, sqlc.narg(remote_url), sqlc.narg(registry_item_id),
    sqlc.narg(json_spec)::jsonb, sqlc.narg(registry_url), sqlc.narg(icon),
    @workspace_id, @created_by, @now, @now
)
RETURNING *;

-- name: SetMCPSpecJSONSpec :execrows
UPDATE mcp_servers SET json_spec = @json_spec::jsonb
WHERE id = @id AND workspace_id = @workspace_id;
