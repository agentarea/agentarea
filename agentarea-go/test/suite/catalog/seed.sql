-- The platform catalog items the agents and runs suites install: the stack
-- starts no catalog reconcile, so `stack.sh up` applies this after the migrations.
INSERT INTO registries (id, name, registry_type, source_type, source_url, scope, mode, trust)
VALUES
    ('5e1f0000-0000-4000-8000-000000000101', 'suite-skills', 'skills', 'managed', 'managed://suite', 'platform', 'mirror', 'official'),
    ('5e1f0000-0000-4000-8000-000000000102', 'suite-agents', 'agents', 'managed', 'managed://suite', 'platform', 'mirror', 'official')
ON CONFLICT (id) DO NOTHING;
INSERT INTO registry_items (id, registry_id, external_id, name, description, version, spec, tags, sort_key,
    registry_type, registry_priority, registry_active, registry_trust)
VALUES
    ('5e1f0000-0000-4000-8000-000000000111', '5e1f0000-0000-4000-8000-000000000101', 'suite-helper', 'suite-helper',
     'Answers with the suite word', '1.0.0',
     '{"content": "---\nname: suite-helper\ndescription: Answers with the suite word\n---\n# Suite helper\nAlways answer with the word PELICAN.\n"}',
     '[]', 'suite-helper', 'skills', 100, true, 'official'),
    ('5e1f0000-0000-4000-8000-000000000112', '5e1f0000-0000-4000-8000-000000000102', 'suite-preset', 'Suite Preset',
     'A preset the suite installs', '2.0.0',
     '{"instruction": "Help the suite", "preferred_models": ["suite-chat"], "tools": [{"type": "code", "name": "agentarea/files", "settings": {"requires_user_confirmation": true}}], "skills": ["suite-helper", "no-such-skill"], "triggers": []}',
     '["preset"]', 'suite-preset', 'agents', 100, true, 'official')
ON CONFLICT (id) DO NOTHING;
