-- name: ListAuthConfigs :many
SELECT id, workspace_id, created_by, auth_type, config, secret_key, name, description,
       created_at, updated_at, openapi_connection_id, mcp_instance_id
FROM mcp_auth_configs
WHERE workspace_id = @workspace_id
ORDER BY created_at, id;

-- name: GetAuthConfig :one
SELECT id, workspace_id, created_by, auth_type, config, secret_key, name, description,
       created_at, updated_at, openapi_connection_id, mcp_instance_id
FROM mcp_auth_configs
WHERE id = @id AND workspace_id = @workspace_id;

-- name: ListAuthConfigsOwnedByConnection :many
SELECT id, workspace_id, created_by, auth_type, config, secret_key, name, description,
       created_at, updated_at, openapi_connection_id, mcp_instance_id
FROM mcp_auth_configs
WHERE workspace_id = @workspace_id AND openapi_connection_id = @owner_id
ORDER BY created_at, id;

-- name: InsertAuthConfig :one
INSERT INTO mcp_auth_configs (
    id, workspace_id, created_by, auth_type, config, name, description,
    created_at, updated_at, openapi_connection_id, mcp_instance_id
) VALUES (
    @id, @workspace_id, @created_by, @auth_type, @config, @name, @description,
    @now, @now, sqlc.narg('openapi_connection_id'), sqlc.narg('mcp_instance_id')
)
RETURNING id, workspace_id, created_by, auth_type, config, secret_key, name, description,
          created_at, updated_at, openapi_connection_id, mcp_instance_id;

-- name: UpdateAuthConfigFields :execrows
UPDATE mcp_auth_configs
SET name = COALESCE(sqlc.narg('name')::text, name),
    description = COALESCE(sqlc.narg('description')::text, description),
    config = COALESCE(sqlc.narg('config')::jsonb, config),
    updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SetAuthConfigSecretKey :execrows
UPDATE mcp_auth_configs
SET secret_key = @secret_key, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: DeleteAuthConfig :execrows
DELETE FROM mcp_auth_configs WHERE id = @id AND workspace_id = @workspace_id;

-- name: LinkedMCPInstanceIDs :many
SELECT id FROM mcp_server_instances
WHERE auth_config_id = @auth_config_id AND workspace_id = @workspace_id
ORDER BY id;

-- name: LinkedOpenAPIConnectionIDs :many
SELECT id FROM openapi_connections
WHERE auth_config_id = @auth_config_id AND workspace_id = @workspace_id
ORDER BY id;
