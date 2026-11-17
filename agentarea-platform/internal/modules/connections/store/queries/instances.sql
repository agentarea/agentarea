-- Instances visible to a workspace: its own and the platform-managed ones.
-- Writes re-assert the strict workspace filter.

-- name: ListInstances :many
SELECT id, workspace_id, created_by, name, description, server_spec_id, transport, json_spec,
       verification, last_dispatch, tools, events, auth_config_id, managed_by, cost,
       created_at, updated_at
FROM mcp_server_instances
WHERE workspace_id = @workspace_id OR managed_by = 'platform'
ORDER BY created_at, id;

-- name: GetInstance :one
SELECT id, workspace_id, created_by, name, description, server_spec_id, transport, json_spec,
       verification, last_dispatch, tools, events, auth_config_id, managed_by, cost,
       created_at, updated_at
FROM mcp_server_instances
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: GetInstancesByIDs :many
SELECT id, workspace_id, created_by, name, description, server_spec_id, transport, json_spec,
       verification, last_dispatch, tools, events, auth_config_id, managed_by, cost,
       created_at, updated_at
FROM mcp_server_instances
WHERE id = ANY(@ids::uuid[]) AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: LockInstance :one
SELECT id, workspace_id, created_by, name, description, server_spec_id, transport, json_spec,
       verification, last_dispatch, tools, events, auth_config_id, managed_by, cost,
       created_at, updated_at
FROM mcp_server_instances
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform')
FOR UPDATE;

-- name: InsertInstance :one
INSERT INTO mcp_server_instances (
    id, workspace_id, created_by, name, description, server_spec_id, transport, json_spec,
    verification, auth_config_id, network_scope, cost, created_at, updated_at
) VALUES (
    @id, @workspace_id, @created_by, @name, sqlc.narg('description'), @server_spec_id, @transport,
    @json_spec, @verification, sqlc.narg('auth_config_id'), 'private', sqlc.narg('cost'), @now, @now
)
RETURNING id, workspace_id, created_by, name, description, server_spec_id, transport, json_spec,
          verification, last_dispatch, tools, events, auth_config_id, managed_by, cost,
          created_at, updated_at;

-- name: UpdateInstance :execrows
UPDATE mcp_server_instances
SET name = @name, description = sqlc.narg('description'), json_spec = @json_spec,
    cost = sqlc.narg('cost'), updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SetInstanceJSONSpec :execrows
UPDATE mcp_server_instances
SET json_spec = @json_spec, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SetInstanceAuthConfig :execrows
UPDATE mcp_server_instances
SET auth_config_id = sqlc.narg('auth_config_id'), updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- Verification writes reach platform-managed rows too: the monitor verifies them.
-- name: SetInstanceVerification :execrows
UPDATE mcp_server_instances
SET verification = @verification
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: SetInstanceDiscovery :execrows
UPDATE mcp_server_instances
SET verification = @verification, tools = sqlc.narg('tools'), events = sqlc.narg('events')
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: SetInstanceLastDispatch :execrows
UPDATE mcp_server_instances
SET last_dispatch = @last_dispatch
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: DeleteInstance :execrows
DELETE FROM mcp_server_instances WHERE id = @id AND workspace_id = @workspace_id;

-- name: InstanceNameTaken :one
SELECT EXISTS (
    SELECT 1 FROM mcp_server_instances
    WHERE workspace_id = @workspace_id AND name = @name AND id <> @except_id
)::bool;

-- Global: the monitor's sweeps and the proxy's workspace binding span workspaces.

-- name: InterruptStaleVerifications :execrows
UPDATE mcp_server_instances
SET verification = @verification
WHERE verification->>'status' = 'in_progress'
  AND (verification->>'at')::timestamptz < @before::timestamptz;

-- name: ListNeverAttempted :many
SELECT id, workspace_id, managed_by FROM mcp_server_instances
WHERE (transport IN ('docker', 'command') OR managed_by = 'platform')
  AND verification->>'status' = 'never_attempted'
ORDER BY created_at, id
LIMIT @max_rows::int;

-- name: ConnectionWorkspace :many
SELECT id, workspace_id, 'mcp'::text AS kind FROM mcp_server_instances WHERE mcp_server_instances.id = @id
UNION ALL
SELECT id, workspace_id, 'openapi'::text AS kind FROM openapi_connections WHERE openapi_connections.id = @id;
