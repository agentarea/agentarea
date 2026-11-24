-- name: InsertAPIKey :one
INSERT INTO api_keys (id, workspace_id, created_by, name, token_hash, token_prefix, expires_at, agent_id, client_id, created_at, updated_at)
VALUES (@id, @workspace_id, @created_by, @name, @token_hash, @token_prefix, @expires_at, @agent_id, @client_id, @now, @now)
RETURNING id, name, token_prefix, is_active, expires_at, access_count, last_accessed_at, created_at, agent_id, client_id;

-- name: GetAPIKey :one
SELECT id, name, token_prefix, is_active, expires_at, access_count, last_accessed_at, created_at, agent_id, created_by, client_id
FROM api_keys WHERE workspace_id = @workspace_id AND id = @id;

-- name: ListAPIKeys :many
SELECT id, name, token_prefix, is_active, expires_at, access_count, last_accessed_at, created_at, agent_id, created_by, client_id
FROM api_keys
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(created_by)::text IS NULL OR created_by = sqlc.narg(created_by)::text)
  AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid)
ORDER BY created_at DESC;

-- name: ListClientAPIKeys :many
SELECT id, name, token_prefix, is_active, expires_at, access_count, last_accessed_at, created_at, agent_id, created_by, client_id
FROM api_keys
WHERE workspace_id = @workspace_id AND client_id = @client_id
ORDER BY created_at DESC;

-- name: DeactivateAPIKey :exec
UPDATE api_keys SET is_active = false, updated_at = @now WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeactivateUserAPIKeys :exec
UPDATE api_keys SET is_active = false, updated_at = @now WHERE workspace_id = @workspace_id AND created_by = @created_by;
