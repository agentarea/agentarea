-- name: SurfaceTask :one
SELECT id, agent_id, description, COALESCE(parameters::text, '')::text AS parameters, status,
    COALESCE(result::text, '')::text AS result, error, started_at, completed_at, execution_id,
    COALESCE(task_metadata::text, '')::text AS task_metadata, created_by, created_at, updated_at,
    scheduled_at, origin_type, origin_id, correlation_id, causation_id, parent_task_id, depth,
    task_definition_id, source_identity
FROM tasks
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SurfaceTaskPage :many
SELECT id, agent_id, description, COALESCE(parameters::text, '')::text AS parameters, status,
    COALESCE(result::text, '')::text AS result, error, started_at, completed_at, execution_id,
    COALESCE(task_metadata::text, '')::text AS task_metadata, created_by, created_at, updated_at,
    scheduled_at, origin_type, origin_id, correlation_id, causation_id, parent_task_id, depth,
    task_definition_id, source_identity
FROM tasks
WHERE workspace_id = @workspace_id
  AND (cardinality(sqlc.arg(statuses)::text[]) = 0 OR status = ANY(sqlc.arg(statuses)::text[]))
  AND (sqlc.narg(created_by)::text IS NULL OR created_by = sqlc.narg(created_by)::text)
  AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid)
  AND (sqlc.narg(search)::text IS NULL
       OR lower(description) LIKE '%' || lower(sqlc.narg(search)::text) || '%' ESCAPE '/'
       OR agent_id = ANY(sqlc.arg(search_agent_ids)::uuid[]))
ORDER BY created_at DESC, id DESC
LIMIT @max_rows OFFSET @skip;

-- name: SurfaceAgentTasks :many
SELECT id, agent_id, description, COALESCE(parameters::text, '')::text AS parameters, status,
    COALESCE(result::text, '')::text AS result, error, started_at, completed_at, execution_id,
    COALESCE(task_metadata::text, '')::text AS task_metadata, created_by, created_at, updated_at,
    scheduled_at, origin_type, origin_id, correlation_id, causation_id, parent_task_id, depth,
    task_definition_id, source_identity
FROM tasks
WHERE workspace_id = @workspace_id AND agent_id = @agent_id
  AND (sqlc.narg(status)::text IS NULL OR status = sqlc.narg(status)::text)
ORDER BY created_at DESC
LIMIT @max_rows OFFSET @skip;

-- name: SurfaceTaskAgentIDs :many
SELECT DISTINCT agent_id FROM tasks WHERE workspace_id = @workspace_id;

-- name: SurfaceInboxPage :many
SELECT id, agent_id, description, COALESCE(parameters::text, '')::text AS parameters, status,
    COALESCE(result::text, '')::text AS result, error, started_at, completed_at, execution_id,
    COALESCE(task_metadata::text, '')::text AS task_metadata, created_by, created_at, updated_at,
    scheduled_at, origin_type, origin_id, correlation_id, causation_id, parent_task_id, depth,
    task_definition_id, source_identity
FROM tasks
WHERE workspace_id = @workspace_id AND status = ANY(sqlc.arg(statuses)::text[])
  AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid)
ORDER BY CASE WHEN status IN ('blocked', 'completed', 'failed', 'cancelled')
    THEN COALESCE(completed_at, updated_at) ELSE updated_at END DESC, id
LIMIT @max_rows OFFSET @skip;

-- name: SurfaceInboxCount :one
SELECT count(id) FROM tasks
WHERE workspace_id = @workspace_id AND status = ANY(sqlc.arg(statuses)::text[])
  AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid);

-- name: SurfaceTaskDescriptions :many
SELECT id, description FROM tasks
WHERE workspace_id = @workspace_id AND id = ANY(sqlc.arg(ids)::uuid[]);

-- name: SurfaceCancelScheduled :execrows
UPDATE tasks SET status = 'cancelled', updated_at = sqlc.arg(now)::timestamp,
    completed_at = CASE WHEN status = 'cancelled' THEN COALESCE(completed_at, sqlc.arg(now)::timestamp)
        ELSE sqlc.arg(now)::timestamp END
WHERE id = @id AND workspace_id = @workspace_id;
