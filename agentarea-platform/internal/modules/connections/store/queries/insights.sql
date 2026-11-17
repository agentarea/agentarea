-- name: InstanceNetworkScopes :many
SELECT id, network_scope FROM mcp_server_instances
WHERE workspace_id = @workspace_id OR managed_by = 'platform';
