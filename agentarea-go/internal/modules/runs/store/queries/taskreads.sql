-- name: TaskStatuses :many
SELECT id, status FROM tasks
WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);

-- name: TaskCosts :many
SELECT id,
    COALESCE(CASE WHEN json_typeof(result) = 'object' THEN result->>'own_cost' END, '')::text AS own_cost,
    COALESCE(CASE WHEN json_typeof(result) = 'object' THEN result->>'total_cost' END, '')::text AS total_cost
FROM tasks
WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);

-- name: UnfinishedRunsFrom :many
SELECT id, execution_id FROM tasks
WHERE workspace_id = @workspace_id
  AND origin_type = @origin_type::text
  AND origin_id = @origin_id::text
  AND status NOT IN ('blocked', 'completed', 'failed', 'cancelled')
ORDER BY created_at;

-- name: TaskOriginOf :one
SELECT origin_type, origin_id, causation_id FROM tasks
WHERE id = @id AND workspace_id = @workspace_id;
