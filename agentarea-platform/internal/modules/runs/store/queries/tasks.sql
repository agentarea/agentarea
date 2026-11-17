-- name: TaskForLog :one
SELECT id, correlation_id, causation_id, status FROM tasks
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SetTaskOutcome :execrows
UPDATE tasks SET
    status = sqlc.arg(status)::text,
    updated_at = sqlc.arg(now)::timestamp,
    started_at = CASE WHEN sqlc.arg(status)::text = 'running'
        THEN COALESCE(started_at, sqlc.arg(now)::timestamp) ELSE started_at END,
    completed_at = CASE
        WHEN sqlc.arg(status)::text NOT IN ('blocked', 'completed', 'failed', 'cancelled') THEN completed_at
        WHEN status = sqlc.arg(status)::text THEN COALESCE(completed_at, sqlc.arg(now)::timestamp)
        ELSE sqlc.arg(now)::timestamp END,
    result = CASE WHEN sqlc.arg(set_result)::bool THEN sqlc.narg(result)::text::json ELSE result END,
    error = CASE WHEN sqlc.arg(set_error)::bool THEN sqlc.narg(error)::text ELSE error END,
    task_metadata = CASE WHEN sqlc.arg(patch_metadata)::bool THEN (
        CASE WHEN jsonb_typeof(task_metadata::jsonb) = 'object' THEN task_metadata::jsonb ELSE '{}'::jsonb END
        || sqlc.arg(metadata_patch)::text::jsonb)::json
        ELSE task_metadata END
WHERE id = @id AND workspace_id = @workspace_id;

-- name: MergeTaskMetadata :execrows
UPDATE tasks SET
    task_metadata = (
        CASE WHEN jsonb_typeof(task_metadata::jsonb) = 'object' THEN task_metadata::jsonb ELSE '{}'::jsonb END
        || sqlc.arg(patch)::text::jsonb)::json,
    updated_at = sqlc.arg(now)::timestamp
WHERE id = @id AND workspace_id = @workspace_id;

-- name: TaskProvenance :one
SELECT id, agent_id, correlation_id, source_identity, project_id FROM tasks
WHERE id = @id AND workspace_id = @workspace_id;

-- name: InsertTask :exec
INSERT INTO tasks (
    id, agent_id, description, parameters, status, execution_id, task_metadata,
    workspace_id, created_by, created_at, updated_at, origin_type, origin_id,
    correlation_id, causation_id, parent_task_id, depth, source_identity
) VALUES (
    @id, @agent_id, @description, sqlc.arg(parameters)::text::json, @status, sqlc.narg(execution_id),
    sqlc.arg(task_metadata)::text::json, @workspace_id, @created_by, sqlc.arg(now)::timestamp,
    sqlc.arg(now)::timestamp, sqlc.narg(origin_type), sqlc.narg(origin_id), sqlc.narg(correlation_id),
    sqlc.narg(causation_id), @parent_task_id, @depth, sqlc.narg(source_identity)
);
