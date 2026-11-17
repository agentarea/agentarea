-- name: GetStream :one
SELECT id, workspace_id, created_by, created_at, name, description, kind FROM streams
WHERE workspace_id = @workspace_id AND id = @id;

-- name: GetStreamByName :one
SELECT id, workspace_id, created_by, created_at, name, description, kind FROM streams
WHERE workspace_id = @workspace_id AND name = @name;

-- name: GetPlatformStream :one
SELECT id, workspace_id, created_by, created_at, name, description, kind FROM streams
WHERE workspace_id = @workspace_id AND kind = 'platform';

-- name: InsertStream :one
INSERT INTO streams (id, workspace_id, created_by, created_at, updated_at, name, description, kind)
VALUES (@id, @workspace_id, @created_by, @now, @now, @name, @description, @kind)
ON CONFLICT ON CONSTRAINT uq_streams_workspace_name DO NOTHING
RETURNING id, workspace_id, created_by, created_at, name, description, kind;

-- name: ListStreams :many
SELECT id, workspace_id, created_by, created_at, name, description, kind FROM streams
WHERE workspace_id = @workspace_id
  AND (NOT @filter_ids::bool OR id = ANY(@ids::uuid[]))
ORDER BY created_at, id
LIMIT @lim OFFSET @off;

-- name: LockStreamForDelete :one
SELECT id, workspace_id, created_by, created_at, name, description, kind FROM streams
WHERE workspace_id = @workspace_id AND id = @id
FOR UPDATE;

-- name: LockExistingStreams :many
SELECT id FROM streams
WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[])
ORDER BY id
FOR KEY SHARE;

-- name: StreamNames :many
SELECT id, name FROM streams WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);

-- name: DeleteStream :execrows
DELETE FROM streams WHERE workspace_id = @workspace_id AND id = @id;
