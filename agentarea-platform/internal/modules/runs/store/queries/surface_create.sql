-- name: SurfaceInsertTask :exec
INSERT INTO tasks (
    id, agent_id, description, parameters, status, task_metadata, workspace_id, created_by,
    created_at, updated_at, scheduled_at, origin_type, origin_id, correlation_id, causation_id,
    parent_task_id, depth, task_definition_id, source_identity
) VALUES (
    @id, @agent_id, @description, sqlc.arg(parameters)::text::json, @status, sqlc.arg(task_metadata)::text::json,
    @workspace_id, @created_by, sqlc.arg(now)::timestamp, sqlc.arg(now)::timestamp, sqlc.narg(scheduled_at)::timestamptz,
    sqlc.narg(origin_type), sqlc.narg(origin_id), sqlc.narg(correlation_id), sqlc.narg(causation_id),
    sqlc.narg(parent_task_id)::uuid, @depth, sqlc.narg(task_definition_id)::uuid, sqlc.narg(source_identity)
);

-- name: SurfaceSetTaskStatus :execrows
UPDATE tasks SET status = @status::varchar, error = sqlc.narg(error), updated_at = sqlc.arg(now)::timestamp,
    completed_at = CASE WHEN @status::varchar = 'failed' THEN sqlc.arg(now)::timestamp ELSE completed_at END
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SurfaceActiveInSession :many
SELECT id, description, parameters::text AS parameters, execution_id, created_by
FROM tasks
WHERE workspace_id = @workspace_id AND agent_id = @agent_id
  AND status IN ('running', 'completed') AND execution_id IS NOT NULL
  AND parameters ->> 'trigger_id' = @trigger_id::text
  AND parameters -> 'session' ->> 'key' = @session_key::text
ORDER BY created_at DESC
LIMIT 5;

-- name: SurfaceConversationOutline :many
SELECT seq, kind, role, COALESCE(jsonb_array_length(CASE WHEN jsonb_typeof(tool_calls) = 'array' THEN tool_calls END), 0)::int AS tool_calls
FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id
ORDER BY seq;
