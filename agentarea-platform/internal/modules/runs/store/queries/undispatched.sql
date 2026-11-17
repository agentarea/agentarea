-- name: UndispatchedTasks :many
SELECT id, workspace_id, created_by FROM tasks
WHERE status = 'pending'
  AND execution_id IS NULL
  AND created_at < sqlc.arg(stale_before)::timestamp
  AND created_at >= sqlc.arg(horizon)::timestamp
  AND (origin_type IS NULL OR origin_type <> 'trigger')
ORDER BY created_at
LIMIT sqlc.arg(max_rows)::int;

-- name: TaskToLaunch :one
SELECT id, agent_id, description, parameters, status, execution_id, task_metadata, created_by, scheduled_at
FROM tasks
WHERE id = @id AND workspace_id = @workspace_id;

-- name: MarkTaskLaunched :execrows
UPDATE tasks SET
    status = sqlc.arg(status)::text,
    execution_id = sqlc.arg(execution_id)::text,
    updated_at = sqlc.arg(now)::timestamp,
    started_at = CASE WHEN sqlc.arg(status)::text = 'running'
        THEN COALESCE(started_at, sqlc.arg(now)::timestamp) ELSE started_at END
WHERE id = @id AND workspace_id = @workspace_id;
