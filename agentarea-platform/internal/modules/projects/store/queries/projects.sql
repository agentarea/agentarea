-- name: CreateProject :one
INSERT INTO projects (id, created_at, updated_at, workspace_id, created_by, name, description, instructions, parent_project_id)
VALUES (@id, @now, @now, @workspace_id, @created_by, @name, @description, @instructions, @parent_project_id)
RETURNING id, workspace_id, created_by, name, description, instructions, parent_project_id;

-- name: GetProject :one
SELECT id, workspace_id, created_by, name, description, instructions, parent_project_id
FROM projects WHERE workspace_id = @workspace_id AND id = @id;

-- ListProjects keeps Python's missing ORDER BY (repository.py list_all).
-- name: ListProjects :many
SELECT id, workspace_id, created_by, name, description, instructions, parent_project_id
FROM projects WHERE workspace_id = @workspace_id
LIMIT @lim OFFSET @off;

-- name: GetInstructions :one
SELECT name, instructions, parent_project_id
FROM projects WHERE workspace_id = @workspace_id AND id = @id;

-- name: UpdateProject :one
UPDATE projects SET
    name = CASE WHEN @set_name::bool THEN @name::varchar ELSE name END,
    description = CASE WHEN @set_description::bool THEN sqlc.narg(description)::text ELSE description END,
    instructions = CASE WHEN @set_instructions::bool THEN sqlc.narg(instructions)::text ELSE instructions END,
    parent_project_id = CASE WHEN @set_parent::bool THEN sqlc.narg(parent_project_id)::uuid ELSE parent_project_id END,
    updated_at = CASE WHEN
        (@set_name AND name IS DISTINCT FROM @name::varchar)
        OR (@set_description AND description IS DISTINCT FROM sqlc.narg(description)::text)
        OR (@set_instructions AND instructions IS DISTINCT FROM sqlc.narg(instructions)::text)
        OR (@set_parent AND parent_project_id IS DISTINCT FROM sqlc.narg(parent_project_id)::uuid)
        THEN @now ELSE updated_at END
WHERE workspace_id = @workspace_id AND id = @id
RETURNING id;

-- name: DeleteProject :execrows
DELETE FROM projects WHERE workspace_id = @workspace_id AND id = @id;
