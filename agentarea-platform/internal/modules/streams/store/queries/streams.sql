-- name: GetStream :one
SELECT st.id, st.workspace_id, st.created_by, st.created_at, st.name, st.description, st.kind,
    ARRAY(SELECT src.webhook_type FROM stream_sources src
          WHERE src.workspace_id = st.workspace_id AND src.stream_id = st.id AND src.webhook_type IS NOT NULL
          GROUP BY src.webhook_type ORDER BY min(src.created_at), src.webhook_type)::text[] AS source_types
FROM streams st
WHERE st.workspace_id = @workspace_id AND st.id = @id;

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
SELECT st.id, st.workspace_id, st.created_by, st.created_at, st.name, st.description, st.kind,
    ARRAY(SELECT src.webhook_type FROM stream_sources src
          WHERE src.workspace_id = st.workspace_id AND src.stream_id = st.id AND src.webhook_type IS NOT NULL
          GROUP BY src.webhook_type ORDER BY min(src.created_at), src.webhook_type)::text[] AS source_types
FROM streams st
WHERE st.workspace_id = @workspace_id
  AND (NOT @filter_ids::bool OR st.id = ANY(@ids::uuid[]))
ORDER BY st.created_at, st.id
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

-- name: SetStreamDescription :execrows
UPDATE streams SET description = @description, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;
