-- name: NetworkAgents :many
SELECT id, name, description, model_id, tools, status FROM agents
WHERE workspace_id = @workspace_id AND status <> 'archived'
ORDER BY created_at, id;

-- name: NetworkAgentNames :many
SELECT id, name FROM agents
WHERE workspace_id = @workspace_id
ORDER BY id::text;

-- name: NetworkAgentSkills :many
SELECT a.agent_id, s.id, s.name FROM agent_skills a
JOIN skills s ON s.id = a.skill_id
WHERE s.workspace_id = @workspace_id
ORDER BY a.agent_id, a.created_at, s.id;

-- name: NetworkSkills :many
SELECT id, name, description, source_type, network_scope FROM skills
WHERE workspace_id = @workspace_id
ORDER BY created_at, id;

-- name: NetworkSkillMembers :many
SELECT m.parent_skill_id, m.child_skill_id FROM skill_members m
JOIN skills p ON p.id = m.parent_skill_id
WHERE p.workspace_id = @workspace_id
ORDER BY m.parent_skill_id, m."order", m.child_skill_id;
