-- name: InsertTaskDef :exec
INSERT INTO task_definitions (id, created_at, updated_at, workspace_id, created_by, name, description, agent_id, parameters)
VALUES (@id, @now, @now, @workspace_id, @created_by, @name, @description, @agent_id, @parameters);

-- name: GetTaskDef :one
SELECT id, created_at, updated_at, workspace_id, created_by, name, description, agent_id, parameters
FROM task_definitions WHERE workspace_id = @workspace_id AND id = @id;

-- name: ListTaskDefs :many
SELECT id, created_at, updated_at, workspace_id, created_by, name, description, agent_id, parameters
FROM task_definitions
WHERE workspace_id = @workspace_id AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid)
ORDER BY created_at DESC
LIMIT @row_limit;

-- name: UpdateTaskDef :exec
UPDATE task_definitions SET name = @name, description = @description, agent_id = @agent_id, parameters = @parameters,
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeleteTaskDef :execrows
DELETE FROM task_definitions WHERE workspace_id = @workspace_id AND id = @id;

-- name: TaskDefAgentStatus :one
SELECT status FROM agents WHERE workspace_id = @workspace_id AND id = @id;
