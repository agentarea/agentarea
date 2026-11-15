-- name: AttachConnectionAuth :execrows
UPDATE openapi_connections
SET auth_config_id = @auth_config_id, status = 'active', updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;
