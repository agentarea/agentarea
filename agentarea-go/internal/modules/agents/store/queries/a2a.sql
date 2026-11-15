-- name: A2AAgent :one
SELECT id, workspace_id, created_by, name, slug, status, description, instruction, model_id, client_id, harness_client_id,
    tools, planning, a2ui_enabled, reasoning_effort, reasoning_max_tokens, answer_check, agent_type, registry_item_id
FROM agents WHERE id = @id;
