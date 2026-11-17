-- name: InsertTaskEvent :exec
INSERT INTO task_events (id, task_id, event_type, "timestamp", data, event_metadata, workspace_id, created_by)
VALUES (@id, @task_id, @event_type, @occurred_at, sqlc.arg(data)::text::jsonb,
    sqlc.arg(event_metadata)::text::jsonb, @workspace_id, @created_by)
ON CONFLICT (id) DO NOTHING;
