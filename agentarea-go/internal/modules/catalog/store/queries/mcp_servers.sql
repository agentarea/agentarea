-- UpdateMirroredServer is _update_mcp_server: the workspace's row the item
-- installed, rewritten from the item.
-- name: UpdateMirroredServer :execrows
UPDATE mcp_servers SET
    description = @description,
    docker_image_url = @docker_image_url,
    version = @version,
    tags = @tags::json,
    env_schema = @env_schema::json,
    cmd = sqlc.narg(cmd)::json,
    remote_url = sqlc.narg(remote_url),
    json_spec = sqlc.narg(json_spec)::jsonb,
    registry_url = @registry_url,
    updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: WorkspaceMCPServers :many
SELECT id, name FROM mcp_servers WHERE workspace_id = @workspace_id ORDER BY created_at DESC;

-- name: WorkspaceMCPServerExists :one
SELECT EXISTS (SELECT 1 FROM mcp_servers WHERE workspace_id = @workspace_id AND id = @id)::bool;
