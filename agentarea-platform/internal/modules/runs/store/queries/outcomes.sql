-- name: OutcomeTask :one
SELECT id, agent_id, created_by, origin_type, origin_id, correlation_id, depth, parameters, task_metadata
FROM tasks WHERE id = @id AND workspace_id = @workspace_id;
