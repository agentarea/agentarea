-- name: MCPInstanceExists :one
SELECT EXISTS (
    SELECT 1 FROM mcp_server_instances
    WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform')
)::bool;

-- name: MCPInstanceNames :many
SELECT id, name FROM mcp_server_instances
WHERE id = ANY(@ids::uuid[]) AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: MCPInstanceFlags :many
SELECT id, managed_by FROM mcp_server_instances
WHERE id = ANY(@ids::uuid[]) AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: OpenAPIConnectionFlags :many
SELECT id, managed_by FROM openapi_connections
WHERE id = ANY(@ids::uuid[]) AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: OpenAPIConnectionNames :many
SELECT id, name FROM openapi_connections
WHERE id = ANY(@ids::uuid[]) AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: MCPInstancesNamed :many
SELECT id, created_by, managed_by FROM mcp_server_instances
WHERE name = @name AND (workspace_id = @workspace_id OR managed_by = 'platform')
ORDER BY created_at DESC;
