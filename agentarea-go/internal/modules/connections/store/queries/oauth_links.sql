-- name: InsertOAuthLink :one
INSERT INTO mcp_oauth_links (
    id, workspace_id, created_by, mcp_instance_id, token, access_control, provider_config,
    is_active, expires_at, access_count, created_at, updated_at
) VALUES (
    @id, @workspace_id, @created_by, @mcp_instance_id, @token, @access_control, @provider_config,
    true, sqlc.narg('expires_at'), 0, @now, @now
)
RETURNING id, workspace_id, created_by, mcp_instance_id, token, access_control, provider_config,
          is_active, expires_at, access_count, last_accessed_at, created_at;

-- name: ListOAuthLinksByInstance :many
SELECT id, workspace_id, created_by, mcp_instance_id, token, access_control, provider_config,
       is_active, expires_at, access_count, last_accessed_at, created_at
FROM mcp_oauth_links
WHERE workspace_id = @workspace_id AND mcp_instance_id = @mcp_instance_id
ORDER BY created_at, id;

-- name: GetOAuthLink :one
SELECT id, workspace_id, created_by, mcp_instance_id, token, access_control, provider_config,
       is_active, expires_at, access_count, last_accessed_at, created_at
FROM mcp_oauth_links
WHERE id = @id AND workspace_id = @workspace_id;

-- name: DeactivateOAuthLink :execrows
UPDATE mcp_oauth_links
SET is_active = false, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;
