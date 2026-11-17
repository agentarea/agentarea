-- name: InsertAuditEvent :exec
INSERT INTO audit_events (id, created_at, updated_at, actor_id, actor_type, workspace_id, source_ip, user_agent,
                          request_id, action, resource_type, resource_id, changes, event_metadata)
VALUES (@id, @now, @now, @actor_id, @actor_type, @workspace_id, sqlc.narg(source_ip)::inet, sqlc.narg(user_agent),
        sqlc.narg(request_id), @action, @resource_type, sqlc.narg(resource_id), sqlc.narg(changes)::jsonb, @event_metadata);

-- InsertAuditEventOnce leaves created_at to the column default, as insert_once
-- sends only the columns the event has set.
-- name: InsertAuditEventOnce :execrows
INSERT INTO audit_events (id, actor_id, actor_type, workspace_id, source_ip, user_agent, request_id,
                          action, resource_type, resource_id, event_metadata)
VALUES (@id, @actor_id, @actor_type, @workspace_id, sqlc.narg(source_ip)::inet, sqlc.narg(user_agent),
        sqlc.narg(request_id), @action, @resource_type, sqlc.narg(resource_id), @event_metadata)
ON CONFLICT (id) DO NOTHING;

-- name: GetAuditCursor :one
SELECT workspace_id, created_at FROM audit_events WHERE id = @id;

-- name: ListAuditEvents :many
SELECT id, created_at, actor_id, actor_type, workspace_id, source_ip, user_agent, request_id,
       action, resource_type, resource_id, changes, event_metadata
FROM audit_events
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(action)::varchar IS NULL OR action = sqlc.narg(action)::varchar)
  AND (sqlc.narg(actor_id)::varchar IS NULL OR actor_id = sqlc.narg(actor_id)::varchar)
  AND (sqlc.narg(resource_type)::varchar IS NULL OR resource_type = sqlc.narg(resource_type)::varchar)
  AND (sqlc.narg(resource_id)::varchar IS NULL OR resource_id = sqlc.narg(resource_id)::varchar)
  AND (sqlc.narg(since)::timestamp IS NULL OR created_at >= sqlc.narg(since)::timestamp)
  AND (sqlc.narg(until)::timestamp IS NULL OR created_at <= sqlc.narg(until)::timestamp)
  AND (NOT @after_cursor::bool OR (created_at, id) < (@cursor_created_at::timestamp, @cursor_id::uuid))
ORDER BY created_at DESC, id DESC
LIMIT @lim;

-- name: ResourceAuditEventsPage :many
SELECT id, created_at, actor_id, actor_type, action, resource_id, event_metadata
FROM audit_events
WHERE workspace_id = @workspace_id AND action = ANY(@actions::varchar[])
  AND resource_type = @resource_type AND resource_id IS NOT NULL
ORDER BY created_at DESC, id DESC
LIMIT @lim OFFSET @off;

-- name: CountResourceAuditEvents :one
SELECT count(*) FROM audit_events
WHERE workspace_id = @workspace_id AND action = ANY(@actions::varchar[])
  AND resource_type = @resource_type AND resource_id IS NOT NULL;
