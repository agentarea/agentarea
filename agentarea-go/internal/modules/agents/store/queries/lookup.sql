-- name: AgentExists :one
SELECT EXISTS (SELECT 1 FROM agents WHERE workspace_id = @workspace_id AND id = @id)::bool;

-- name: SkillExists :one
SELECT EXISTS (SELECT 1 FROM skills WHERE workspace_id = @workspace_id AND id = @id)::bool;

-- name: AgentNames :many
SELECT id, name FROM agents WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);

-- name: SkillNames :many
SELECT id, name FROM skills WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);

-- name: AgentIDBySlug :one
SELECT id FROM agents WHERE workspace_id = @workspace_id AND slug = @slug;
