-- The catalog rows the models and runs suites run against: the stack starts no
-- catalog reconcile, so `stack.sh up` applies this after the migrations.
INSERT INTO provider_specs (id, provider_key, name, provider_type, is_builtin, workspace_id, created_by,
    requires_api_key, base_url, transport, auth, list_shape, reasoning_param, icon)
VALUES ('5e1f0000-0000-4000-8000-000000000001', 'suite-openai', 'Suite OpenAI', 'openai', true, 'platform', 'system',
    true, 'https://api.invalid/v1', 'openai', 'bearer', 'data_id', 'reasoning_effort', 'openai')
ON CONFLICT (id) DO NOTHING;
INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, is_active, workspace_id, created_by, kind,
    context_window, input_cost_per_token, output_cost_per_token)
VALUES
    ('5e1f0000-0000-4000-8000-000000000002', '5e1f0000-0000-4000-8000-000000000001', 'suite-chat', 'Suite Chat', true,
     'platform', 'system', 'chat', 8000, 0.000001, 0.000002),
    ('5e1f0000-0000-4000-8000-000000000003', '5e1f0000-0000-4000-8000-000000000001', 'suite-embed', 'Suite Embed', true,
     'platform', 'system', 'embedding', 512, 0.0000001, 0)
ON CONFLICT (id) DO NOTHING;
