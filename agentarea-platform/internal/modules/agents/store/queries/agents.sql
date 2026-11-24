-- name: InsertAgent :exec
INSERT INTO agents (id, created_at, updated_at, workspace_id, created_by, name, slug, status, description, instruction,
    model_id, client_id, harness_client_id, tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens,
    answer_check, agent_type, registry_item_id)
VALUES (@id, @now, @now, @workspace_id, @created_by, @name, @slug, @status, @description, @instruction,
    @model_id, @client_id, @harness_client_id, @tools, @planning, @a2ui_enabled, @reasoning_effort, @reasoning_max_tokens,
    @answer_check, @agent_type, @registry_item_id);

-- name: GetAgent :one
SELECT id, workspace_id, created_by, name, slug, status, description, instruction, model_id, client_id, harness_client_id,
    tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens, answer_check, agent_type, registry_item_id
FROM agents WHERE workspace_id = @workspace_id AND id = @id;

-- name: GetAgentBySlug :one
SELECT id, workspace_id, created_by, name, slug, status, description, instruction, model_id, client_id, harness_client_id,
    tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens, answer_check, agent_type, registry_item_id
FROM agents WHERE workspace_id = @workspace_id AND slug = @slug;

-- name: GetAgentByRegistryItem :one
SELECT id, workspace_id, created_by, name, slug, status, description, instruction, model_id, client_id, harness_client_id,
    tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens, answer_check, agent_type, registry_item_id
FROM agents WHERE workspace_id = @workspace_id AND registry_item_id = @registry_item_id;

-- name: ListAgents :many
SELECT id, workspace_id, created_by, name, slug, status, description, instruction, model_id, client_id, harness_client_id,
    tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens, answer_check, agent_type, registry_item_id
FROM agents WHERE workspace_id = @workspace_id
ORDER BY created_at DESC;

-- name: ListAgentsByHarnessClient :many
SELECT id, workspace_id, created_by, name, slug, status, description, instruction, model_id, client_id, harness_client_id,
    tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens, answer_check, agent_type, registry_item_id
FROM agents WHERE workspace_id = @workspace_id AND harness_client_id = @harness_client_id
ORDER BY created_at DESC;

-- name: UpdateAgent :exec
UPDATE agents SET name = @name, description = @description, instruction = @instruction, model_id = @model_id,
    client_id = @client_id, tools = @tools, planning = @planning, a2ui_enabled = @a2ui_enabled,
    reasoning_effort = @reasoning_effort, reasoning_max_tokens = @reasoning_max_tokens, answer_check = @answer_check,
    agent_type = @agent_type, status = @status, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeleteAgent :execrows
DELETE FROM agents WHERE workspace_id = @workspace_id AND id = @id;

-- name: AgentSkillRows :many
SELECT s.id, s.name, s.description, s.source_type, s.s3_path, s.registry_item_id
FROM agent_skills a JOIN skills s ON s.id = a.skill_id
WHERE a.agent_id = @agent_id AND s.workspace_id = @workspace_id
ORDER BY s.created_at;

-- name: DeleteAgentSkills :exec
DELETE FROM agent_skills WHERE agent_id = @agent_id;

-- name: InsertAgentSkill :exec
INSERT INTO agent_skills (agent_id, skill_id, created_at) VALUES (@agent_id, @skill_id, @now);

-- name: ClientsForAgents :many
SELECT id, name, kind, default_model FROM clients WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[]);

-- name: CountAgentsOfClient :one
SELECT count(*)::bigint FROM agents WHERE workspace_id = @workspace_id AND client_id = @client_id;
