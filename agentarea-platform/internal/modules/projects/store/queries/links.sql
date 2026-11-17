-- Link rows carry no workspace: every statement reaches them through a
-- project of the session's workspace.

-- name: SkillLinks :many
SELECT l.project_id, l.skill_id AS child_id FROM project_skills l
JOIN projects p ON p.id = l.project_id AND p.workspace_id = @workspace_id
WHERE l.project_id = ANY(@project_ids::uuid[]);

-- name: AgentLinks :many
SELECT l.project_id, l.agent_id AS child_id FROM project_agents l
JOIN projects p ON p.id = l.project_id AND p.workspace_id = @workspace_id
WHERE l.project_id = ANY(@project_ids::uuid[]);

-- name: MCPInstanceLinks :many
SELECT l.project_id, l.mcp_instance_id AS child_id FROM project_mcp_instances l
JOIN projects p ON p.id = l.project_id AND p.workspace_id = @workspace_id
WHERE l.project_id = ANY(@project_ids::uuid[]);

-- name: AddSkill :exec
INSERT INTO project_skills (project_id, skill_id)
SELECT p.id, @child_id FROM projects p WHERE p.workspace_id = @workspace_id AND p.id = @project_id
ON CONFLICT DO NOTHING;

-- name: AddAgent :exec
INSERT INTO project_agents (project_id, agent_id)
SELECT p.id, @child_id FROM projects p WHERE p.workspace_id = @workspace_id AND p.id = @project_id
ON CONFLICT DO NOTHING;

-- name: AddMCPInstance :exec
INSERT INTO project_mcp_instances (project_id, mcp_instance_id)
SELECT p.id, @child_id FROM projects p WHERE p.workspace_id = @workspace_id AND p.id = @project_id
ON CONFLICT DO NOTHING;

-- name: RemoveSkill :exec
DELETE FROM project_skills l USING projects p
WHERE p.id = l.project_id AND p.workspace_id = @workspace_id
  AND l.project_id = @project_id AND l.skill_id = @child_id;

-- name: RemoveAgent :exec
DELETE FROM project_agents l USING projects p
WHERE p.id = l.project_id AND p.workspace_id = @workspace_id
  AND l.project_id = @project_id AND l.agent_id = @child_id;

-- name: RemoveMCPInstance :exec
DELETE FROM project_mcp_instances l USING projects p
WHERE p.id = l.project_id AND p.workspace_id = @workspace_id
  AND l.project_id = @project_id AND l.mcp_instance_id = @child_id;

-- name: AgentProjectIDs :many
SELECT l.project_id FROM project_agents l
JOIN projects p ON p.id = l.project_id AND p.workspace_id = @workspace_id
WHERE l.agent_id = @agent_id
ORDER BY l.project_id;
