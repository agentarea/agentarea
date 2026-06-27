
-- Database setup for real infrastructure testing
-- Run this to create the necessary test data

-- 1. Create test workspace (if not exists)
INSERT INTO workspaces (id, name, description, created_at, updated_at)
VALUES ('test-workspace-id', 'Test Workspace', 'Workspace for integration testing', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 2. Create test user (if not exists)  
INSERT INTO users (id, email, name, created_at, updated_at)
VALUES ('test-user-id', 'test@example.com', 'Test User', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 3. Create provider spec for Ollama
INSERT INTO provider_specs (id, provider_type, name, description, config_schema, created_at, updated_at)
VALUES ('ollama-provider-spec', 'ollama_chat', 'Ollama Chat', 'Local Ollama provider', '{}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 4. Create provider config for Ollama
INSERT INTO provider_configs (id, provider_spec_id, name, config, api_key, created_at, updated_at)
VALUES ('ollama-provider-config', 'ollama-provider-spec', 'Local Ollama', '{"endpoint_url": "http://localhost:11434"}', NULL, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 5. Create model spec for qwen2.5
INSERT INTO model_specs (id, model_name, description, config_schema, created_at, updated_at)
VALUES ('qwen25-model-spec', 'qwen2.5', 'Qwen 2.5 model', '{}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 6. Create model instance
INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, config, created_at, updated_at)
VALUES ('test-model-instance-id', 'ollama-provider-config', 'qwen25-model-spec', 'Test Qwen 2.5', '{}', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 7. Create test agent
INSERT INTO agents (id, workspace_id, name, description, instruction, model_id, tools_config, events_config, planning, created_by, created_at, updated_at)
VALUES ('test-agent-id', 'test-workspace-id', 'Test Agent', 'Agent for integration testing', 'You are a helpful AI assistant. When you complete a task, use the task_complete tool.', 'test-model-instance-id', '{}', '{}', false, 'test-user-id', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- Query to verify setup
SELECT 
    a.id as agent_id,
    a.name as agent_name,
    mi.id as model_instance_id,
    mi.name as model_name,
    pc.name as provider_name,
    ps.provider_type
FROM agents a
JOIN model_instances mi ON a.model_id = mi.id
JOIN provider_configs pc ON mi.provider_config_id = pc.id  
JOIN provider_specs ps ON pc.provider_spec_id = ps.id
WHERE a.id = 'test-agent-id';
