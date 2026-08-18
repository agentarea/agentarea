INSERT INTO data_planes (
    id, display_name, region, state, desired_state, capabilities,
    created_at, updated_at, workspace_id, created_by
) VALUES (
    '11111111-1111-4111-8111-111111111111', 'Timeweb plain VM E2E', 'timeweb',
    'pending', 'active', '{}'::json, now(), now(), 'plain-vm-e2e', 'e2e'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO data_plane_enrollment_tokens (
    id, data_plane_id, token_hash, token_prefix, expires_at, used_at,
    created_at, updated_at, workspace_id, created_by
) VALUES (
    '11111111-1111-4111-8111-111111111112',
    '11111111-1111-4111-8111-111111111111',
    '2f35e22182bcd5a1553244d7294677c6bce958bb9bcf8c7d839d7065bc637ed3',
    'agentarea-e2e-en', '2099-01-01 00:00:00', NULL,
    now(), now(), 'plain-vm-e2e', 'e2e'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO mcp_servers (
    id, name, slug, description, docker_image_url, version, tags, status,
    is_public, env_schema, cmd, workspace_id, created_by, created_at, updated_at,
    json_spec
) VALUES (
    '22222222-2222-4222-8222-222222222222', 'Plain VM whoami', 'plain-vm-whoami',
    'Outbound connector E2E target', 'agentarea/weather-mcp:local', 'e2e',
    '[]'::json, 'active', false, '[]'::json, NULL,
    'plain-vm-e2e', 'e2e', now(), now(),
    '{"type":"docker","image":"agentarea/weather-mcp:local","port":8123}'::jsonb
) ON CONFLICT (id) DO UPDATE SET
    docker_image_url = EXCLUDED.docker_image_url, json_spec = EXCLUDED.json_spec,
    updated_at = now();

INSERT INTO mcp_server_instances (
    id, server_spec_id, name, description, json_spec, workspace_id, created_by,
    created_at, updated_at, verification, network_scope
) VALUES (
    '33333333-3333-4333-8333-333333333333',
    '22222222-2222-4222-8222-222222222222', 'Plain VM whoami instance',
    'Runs through the outbound connector on the Timeweb VM',
    '{}'::json, 'plain-vm-e2e', 'e2e', now(), now(), '{}'::json, 'private'
) ON CONFLICT (id) DO UPDATE SET json_spec = EXCLUDED.json_spec, updated_at = now();
