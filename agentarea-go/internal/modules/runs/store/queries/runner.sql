-- name: RunnerTask :one
SELECT id, agent_id, parameters, task_metadata, created_by, source_identity
FROM tasks
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SetRunnerSession :execrows
UPDATE tasks SET
    task_metadata = (
        CASE WHEN jsonb_typeof(task_metadata::jsonb) = 'object' THEN task_metadata::jsonb ELSE '{}'::jsonb END
        || jsonb_build_object('runner_session_id', sqlc.arg(session_id)::text))::json,
    updated_at = sqlc.arg(now)::timestamp
WHERE id = @id AND workspace_id = @workspace_id
  AND (task_metadata::jsonb ->> 'runner_session_id') IS DISTINCT FROM sqlc.arg(session_id)::text;
