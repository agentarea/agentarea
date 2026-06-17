\set ON_ERROR_STOP on

DO $$
DECLARE
    batch text := to_char(clock_timestamp(), 'YYYYMMDDHH24MISS');
    target_workspaces text[] := ARRAY[
        '51a62cf9-453a-4dc4-9b3f-3e312afe2ff8',
        '1cf4e31c-900b-4bf7-aeb7-27779927a066'
    ];
    ws text;
    creator text;
    provider_spec uuid;
    model_spec uuid;
    provider_config_id uuid;
    model_instance_id uuid;
    skill_ids uuid[];
    agent_ids uuid[];
    project_ids uuid[];
    task_ids uuid[];
    mcp_server_ids uuid[];
    mcp_instance_ids uuid[];
    trigger_ids uuid[];
    new_id uuid;
    parent_skill_id uuid;
    st text;
    flow text;
    icp text;
    artifact_kind text;
    i int;
    task_id uuid;
    agent_id uuid;
    project_id uuid;
    trigger_id uuid;
    statuses text[] := ARRAY['pending', 'running', 'completed', 'failed', 'cancelled', 'blocked', 'submitted'];
    flows text[] := ARRAY[
        'составить КП для enterprise клиента',
        'подготовить налоговый чеклист по транзакциям',
        'сгенерировать DOCX отчет с выводами',
        'сделать презентацию для партнеров',
        'проверить договор и выделить риски',
        'собрать SEO/content strategy',
        'импортировать skill из GitHub repo',
        'импортировать skill из публичной страницы',
        'запустить sandbox и сохранить artifact',
        'проверить OpenAPI tools discovery',
        'создать n8n workflow через MCP',
        'разобрать failed task по логам',
        'сформировать ICP battlecard',
        'сделать PDF/OCR extraction',
        'подготовить customer support response',
        'создать trigger для webhook',
        'проверить governance policy',
        'собрать release pipeline audit',
        'подготовить investor update',
        'сформировать финмодель пилота'
    ];
    icps text[] := ARRAY['CTO', 'VP Engineering', 'AI Platform Lead', 'Security Lead', 'Founder', 'RevOps', 'Sales', 'Finance', 'Legal', 'Customer Success'];
    artifacts text[] := ARRAY['docx', 'pptx', 'pdf', 'xlsx', 'markdown', 'json', 'csv'];
    skill_names text[] := ARRAY[
        'DOCX Proposal Writer',
        'Tax Checklist Analyst',
        'Contract Risk Reviewer',
        'ICP Battlecard Builder',
        'SEO Cluster Researcher',
        'OpenAPI Tool Mapper',
        'MCP Server Designer',
        'Sandbox Artifact Runner',
        'PDF OCR Cleaner',
        'PPTX Deck Generator',
        'Spreadsheet Modeler',
        'Support Reply Drafter',
        'Governance Policy Auditor',
        'Trigger Workflow Tester',
        'Release Pipeline Reviewer',
        'N8N Workflow Builder',
        'Airtable Ops Builder',
        'Qdrant MCP Searcher',
        'Brand Guidelines Applier',
        'Founder Update Writer',
        'Customer Research Planner',
        'AI Coding Coach',
        'Security Questionnaire Helper',
        'Invoice Reconciliation Analyst'
    ];
    agent_names text[] := ARRAY[
        'Commercial Proposal Agent',
        'Tax and Finance Agent',
        'Legal Review Agent',
        'Marketing Strategy Agent',
        'Product Discovery Agent',
        'UI Flow QA Agent',
        'Skill Import Agent',
        'DOCX Artifact Agent',
        'Sandbox Runtime Agent',
        'OpenAPI Integration Agent',
        'MCP Operations Agent',
        'Trigger Automation Agent',
        'Governance Audit Agent',
        'Customer Support Agent',
        'Release Engineering Agent',
        'ICP Research Agent'
    ];
BEGIN
    SELECT ps.id INTO provider_spec
    FROM provider_specs ps
    WHERE ps.provider_key = 'openrouter'
    LIMIT 1;

    SELECT ms.id INTO model_spec
    FROM model_specs ms
    JOIN provider_specs ps ON ps.id = ms.provider_spec_id
    WHERE ps.provider_key = 'openrouter'
      AND ms.model_name ILIKE '%gpt-4o-mini%'
    ORDER BY ms.model_name
    LIMIT 1;

    IF provider_spec IS NULL OR model_spec IS NULL THEN
        RAISE EXCEPTION 'OpenRouter provider/model spec is required for QA seed';
    END IF;

    FOREACH ws IN ARRAY target_workspaces LOOP
        creator := ws;
        skill_ids := ARRAY[]::uuid[];
        agent_ids := ARRAY[]::uuid[];
        project_ids := ARRAY[]::uuid[];
        task_ids := ARRAY[]::uuid[];
        mcp_server_ids := ARRAY[]::uuid[];
        mcp_instance_ids := ARRAY[]::uuid[];
        trigger_ids := ARRAY[]::uuid[];

        INSERT INTO workspaces (id, type, name, owner_user_id, slug, created_at, updated_at)
        VALUES (
            ws,
            'personal',
            'QA Seed Workspace ' || left(ws, 8),
            creator,
            'qa-seed-' || left(ws, 8),
            now(),
            now()
        )
        ON CONFLICT (id) DO UPDATE
        SET updated_at = excluded.updated_at;

        INSERT INTO workspace_memberships (id, workspace_id, user_id, invitation_id, created_at, updated_at)
        VALUES (gen_random_uuid(), ws, creator, NULL, now(), now())
        ON CONFLICT DO NOTHING;

        INSERT INTO provider_configs (
            id, provider_spec_id, name, description, api_key, endpoint_url,
            is_active, is_public, workspace_id, created_by, created_at, updated_at
        )
        VALUES (
            gen_random_uuid(),
            provider_spec,
            'QA Seed OpenRouter ' || batch,
            'Synthetic provider config for UI flow testing. API key is intentionally fake.',
            'qa-seed-openrouter-key-' || batch,
            'https://openrouter.ai/api/v1',
            true,
            false,
            ws,
            creator,
            now(),
            now()
        )
        RETURNING id INTO provider_config_id;

        INSERT INTO model_instances (
            id, provider_config_id, model_spec_id, name, description,
            is_active, is_public, workspace_id, created_by, created_at, updated_at
        )
        VALUES (
            gen_random_uuid(),
            provider_config_id,
            model_spec,
            'QA Seed GPT-4o Mini ' || batch,
            'Synthetic model instance for agents generated by seed_qa_demo_data.sql.',
            true,
            false,
            ws,
            creator,
            now(),
            now()
        )
        RETURNING id INTO model_instance_id;

        FOR i IN 1..24 LOOP
            INSERT INTO skills (
                id, name, slug, description, source_type, source_url, content, s3_path,
                workspace_id, created_by, created_at, updated_at, network_scope
            )
            VALUES (
                gen_random_uuid(),
                'QA Seed ' || skill_names[i] || ' ' || batch,
                'qa-seed-' || lower(replace(skill_names[i], ' ', '-')) || '-' || batch,
                'QA Seed skill for flow testing: ' || skill_names[i] || '.',
                CASE WHEN i % 5 = 0 THEN 'github' ELSE 'content' END,
                CASE
                    WHEN i % 5 = 0 THEN 'https://github.com/agentarea/qa-seed-skills/tree/main/skills/' || lower(replace(skill_names[i], ' ', '-'))
                    WHEN i % 7 = 0 THEN 'https://www.ui-skills.com/skills/qa/seed-' || i || '/'
                    ELSE NULL
                END,
                '---' || chr(10) ||
                'name: qa-seed-' || lower(replace(skill_names[i], ' ', '-')) || chr(10) ||
                'description: Synthetic QA seed skill for AgentArea UI flow testing.' || chr(10) ||
                '---' || chr(10) || chr(10) ||
                '# ' || skill_names[i] || chr(10) || chr(10) ||
                'Use this skill to test realistic AgentArea workflows. Batch: ' || batch || '.',
                CASE WHEN i % 6 = 0 THEN 'artifacts/skills/' || ws || '/qa-seed-' || batch || '/skill-' || i || '/SKILL.md' ELSE NULL END,
                ws,
                creator,
                now() - make_interval(hours => i),
                now() - make_interval(hours => i - 1),
                CASE WHEN i % 4 = 0 THEN 'shared' ELSE 'private' END
            )
            RETURNING id INTO new_id;
            skill_ids := array_append(skill_ids, new_id);
        END LOOP;

        parent_skill_id := skill_ids[1];
        FOR i IN 2..6 LOOP
            INSERT INTO skill_members (parent_skill_id, child_skill_id, "order", is_required, dependencies)
            VALUES (
                parent_skill_id,
                skill_ids[i],
                i - 1,
                i % 2 = 0,
                CASE WHEN i > 3 THEN json_build_array(skill_ids[i - 1]::text) ELSE '[]'::json END
            )
            ON CONFLICT DO NOTHING;
        END LOOP;

        FOR i IN 1..16 LOOP
            INSERT INTO agents (
                id, name, slug, status, description, instruction, model_id, tools, events_config,
                planning, a2ui_enabled, agent_type, registry_item_id,
                workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                'QA Seed ' || agent_names[i] || ' ' || batch,
                'qa-seed-' || lower(replace(agent_names[i], ' ', '-')) || '-' || batch,
                CASE WHEN i % 11 = 0 THEN 'paused' ELSE 'active' END,
                'Synthetic QA agent for ' || icps[((i - 1) % array_length(icps, 1)) + 1] || ' flow coverage.',
                'You are a QA seed agent. Handle realistic tasks, use tools when relevant, preserve artifacts, and explain completion state. Batch: ' || batch || '.',
                model_instance_id::text,
                CASE
                    WHEN i % 4 = 0 THEN json_build_array(
                        json_build_object('type', 'code', 'name', 'agentarea/shell', 'settings', json_build_object('requires_user_confirmation', false)),
                        json_build_object('type', 'code', 'name', 'agentarea/files'),
                        json_build_object('type', 'code', 'name', 'agentarea/skills')
                    )
                    WHEN i % 4 = 1 THEN json_build_array(
                        json_build_object('type', 'code', 'name', 'agentarea/web'),
                        json_build_object('type', 'openapi', 'name', 'qa-seed-openapi-' || i)
                    )
                    WHEN i % 4 = 2 THEN json_build_array(
                        json_build_object('type', 'mcp', 'name', 'qa-seed-mcp-' || i),
                        json_build_object('type', 'code', 'name', 'agentarea/tasks')
                    )
                    ELSE json_build_array(json_build_object('type', 'code', 'name', 'agentarea/skills'))
                END,
                json_build_object('events', json_build_array('task.created', 'task.completed', 'artifact.created')),
                i % 3 = 0,
                i % 5 = 0,
                CASE WHEN i % 6 = 0 THEN 'stateful' ELSE 'stateless' END,
                NULL,
                ws,
                creator,
                now() - make_interval(days => i),
                now() - make_interval(days => i, hours => -1)
            )
            RETURNING id INTO new_id;
            agent_ids := array_append(agent_ids, new_id);

            INSERT INTO agent_skills (agent_id, skill_id, created_at)
            VALUES
                (new_id, skill_ids[((i - 1) % array_length(skill_ids, 1)) + 1], now()),
                (new_id, skill_ids[(i % array_length(skill_ids, 1)) + 1], now())
            ON CONFLICT DO NOTHING;
        END LOOP;

        FOR i IN 1..10 LOOP
            INSERT INTO projects (
                id, name, description, instructions, parent_project_id,
                workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                'QA Seed Project ' || lpad(i::text, 2, '0') || ' ' || batch,
                'Synthetic project containing agents, skills, tasks, and files for UI flow testing.',
                'Use this project to test project detail, agent attachment, skill attachment, and task routing flows. ICP: ' || icps[((i - 1) % array_length(icps, 1)) + 1] || '.',
                NULL,
                ws,
                creator,
                now() - make_interval(days => i),
                now()
            )
            RETURNING id INTO new_id;
            project_ids := array_append(project_ids, new_id);

            INSERT INTO project_agents (project_id, agent_id)
            VALUES
                (new_id, agent_ids[((i - 1) % array_length(agent_ids, 1)) + 1]),
                (new_id, agent_ids[(i % array_length(agent_ids, 1)) + 1])
            ON CONFLICT DO NOTHING;

            INSERT INTO project_skills (project_id, skill_id)
            VALUES
                (new_id, skill_ids[((i - 1) % array_length(skill_ids, 1)) + 1]),
                (new_id, skill_ids[(i % array_length(skill_ids, 1)) + 1])
            ON CONFLICT DO NOTHING;
        END LOOP;

        FOR i IN 1..5 LOOP
            INSERT INTO openapi_connections (
                id, workspace_id, created_by, name, description, spec_url, spec_content, base_url,
                auth_config_id, custom_headers, available_tools, status, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                ws,
                creator,
                'QA Seed OpenAPI ' || i || ' ' || batch,
                'Synthetic OpenAPI connection for testing connection detail and tool discovery.',
                'https://example.com/qa-seed/openapi-' || i || '.json',
                jsonb_build_object(
                    'openapi', '3.1.0',
                    'info', jsonb_build_object('title', 'QA Seed API ' || i, 'version', '1.0.0'),
                    'paths', jsonb_build_object('/items', jsonb_build_object('get', jsonb_build_object('operationId', 'listItems' || i)))
                ),
                'https://api' || i || '.qa-seed.local',
                NULL,
                json_build_array(json_build_object('name', 'X-QA-Seed', 'value', batch, 'secret', false)),
                jsonb_build_array(
                    jsonb_build_object('name', 'listItems' || i, 'description', 'List QA seed items', 'method', 'GET', 'path', '/items'),
                    jsonb_build_object('name', 'createItem' || i, 'description', 'Create QA seed item', 'method', 'POST', 'path', '/items')
                ),
                CASE WHEN i = 5 THEN 'error' ELSE 'active' END,
                now() - make_interval(hours => i),
                now()
            );
        END LOOP;

        FOR i IN 1..6 LOOP
            INSERT INTO mcp_servers (
                id, name, slug, description, docker_image_url, version, tags, status, is_public,
                env_schema, cmd, remote_url, registry_item_id, json_spec, registry_url,
                workspace_id, created_by, updated_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                'QA Seed MCP Server ' || i || ' ' || batch,
                'qa-seed-mcp-server-' || i || '-' || batch,
                'Synthetic MCP server spec for manager, auth, and tool-discovery UI testing.',
                CASE WHEN i % 2 = 0 THEN 'agentarea/qa-seed-mcp:' || i ELSE NULL END,
                '1.0.' || i,
                json_build_array('qa-seed', 'mcp', icps[((i - 1) % array_length(icps, 1)) + 1]),
                CASE WHEN i % 3 = 0 THEN 'draft' ELSE 'ready' END,
                false,
                json_build_array(json_build_object('name', 'QA_SEED_TOKEN', 'required', i % 2 = 0, 'description', 'Synthetic token')),
                CASE WHEN i % 2 = 0 THEN json_build_array('node', 'server.js') ELSE NULL END,
                CASE WHEN i % 2 = 1 THEN 'https://mcp' || i || '.qa-seed.local/mcp' ELSE NULL END,
                NULL,
                jsonb_build_object('name', 'qa-seed-mcp-' || i, 'transport', CASE WHEN i % 2 = 1 THEN 'http' ELSE 'stdio' END),
                'https://registry.qa-seed.local',
                ws,
                creator,
                creator,
                now() - make_interval(hours => i),
                now()
            )
            RETURNING id INTO new_id;
            mcp_server_ids := array_append(mcp_server_ids, new_id);

            INSERT INTO mcp_server_instances (
                id, server_spec_id, name, description, json_spec, verification, last_dispatch, tools,
                network_scope, auth_config_id, workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                new_id::text,
                'QA Seed MCP Instance ' || i || ' ' || batch,
                'Synthetic MCP instance for testing ready/error/auth states.',
                json_build_object(
                    'type', CASE WHEN i % 2 = 1 THEN 'url' ELSE 'docker' END,
                    'endpoint_url', CASE WHEN i % 2 = 1 THEN 'https://mcp' || i || '.qa-seed.local/mcp' ELSE NULL END,
                    'image', CASE WHEN i % 2 = 0 THEN 'agentarea/qa-seed-mcp:' || i ELSE NULL END,
                    'env_vars', json_build_array('QA_SEED_TOKEN')
                ),
                jsonb_build_object('status', CASE WHEN i = 6 THEN 'failed' ELSE 'verified' END, 'checked_at', now()::text),
                jsonb_build_object('status', CASE WHEN i = 6 THEN 'error' ELSE 'ok' END, 'latency_ms', 40 + i * 7),
                jsonb_build_array(
                    jsonb_build_object('name', 'qa_seed_search_' || i, 'description', 'Search QA seed data'),
                    jsonb_build_object('name', 'qa_seed_write_' || i, 'description', 'Write QA seed artifact')
                ),
                CASE WHEN i % 3 = 0 THEN 'shared' ELSE 'private' END,
                NULL,
                ws,
                creator,
                now() - make_interval(hours => i),
                now()
            )
            RETURNING id INTO new_id;
            mcp_instance_ids := array_append(mcp_instance_ids, new_id);
        END LOOP;

        FOR i IN 1..10 LOOP
            INSERT INTO project_mcp_instances (project_id, mcp_instance_id)
            VALUES (project_ids[i], mcp_instance_ids[((i - 1) % array_length(mcp_instance_ids, 1)) + 1])
            ON CONFLICT DO NOTHING;
        END LOOP;

        FOR i IN 1..120 LOOP
            st := statuses[((i - 1) % array_length(statuses, 1)) + 1];
            flow := flows[((i - 1) % array_length(flows, 1)) + 1];
            icp := icps[((i - 1) % array_length(icps, 1)) + 1];
            artifact_kind := artifacts[((i - 1) % array_length(artifacts, 1)) + 1];
            agent_id := agent_ids[((i - 1) % array_length(agent_ids, 1)) + 1];
            project_id := project_ids[((i - 1) % array_length(project_ids, 1)) + 1];

            INSERT INTO tasks (
                id, agent_id, description, parameters, status, result, error, started_at, completed_at,
                execution_id, user_id, task_metadata, project_id,
                workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                agent_id,
                'QA Seed ' || batch || ' #' || lpad(i::text, 3, '0') || ': ' || flow || ' for ' || icp || '.',
                json_build_object(
                    'qa_seed', true,
                    'flow', flow,
                    'icp', icp,
                    'expected_artifact', artifact_kind,
                    'priority', CASE WHEN i % 5 = 0 THEN 'high' WHEN i % 3 = 0 THEN 'medium' ELSE 'low' END,
                    'files', json_build_array('brief-' || i || '.md', 'source-' || i || '.pdf')
                ),
                st,
                CASE
                    WHEN st = 'completed' THEN json_build_object('response', 'Completed QA seed flow: ' || flow, 'total_cost', round((0.02 + i * 0.003)::numeric, 4), 'artifact_kind', artifact_kind)
                    WHEN st = 'running' THEN json_build_object('progress', (i % 90) + 5, 'current_step', 'executing tool calls')
                    ELSE NULL
                END,
                CASE
                    WHEN st = 'failed' THEN 'QA seed synthetic failure: provider timeout while testing ' || flow
                    WHEN st = 'blocked' THEN 'QA seed synthetic blocker: waiting for human approval'
                    ELSE NULL
                END,
                CASE WHEN st IN ('running', 'completed', 'failed', 'cancelled', 'blocked') THEN now() - make_interval(hours => (i % 72) + 1) ELSE NULL END,
                CASE WHEN st IN ('completed', 'failed', 'cancelled') THEN now() - make_interval(hours => (i % 48)) ELSE NULL END,
                'qa-seed-task-' || batch || '-' || i,
                creator,
                json_build_object(
                    'qa_seed_batch', batch,
                    'scenario_id', 'QA-' || lpad(i::text, 3, '0'),
                    'artifact_path', 'artifacts/qa-seed/' || batch || '/task-' || i || '/result.' || artifact_kind,
                    'source', 'scripts/seed_qa_demo_data.sql'
                ),
                project_id,
                ws,
                creator,
                now() - make_interval(hours => i),
                now() - make_interval(mins => i % 60)
            )
            RETURNING id INTO task_id;
            task_ids := array_append(task_ids, task_id);

            INSERT INTO task_events (id, task_id, event_type, timestamp, data, event_metadata, workspace_id, created_by)
            VALUES
                (gen_random_uuid(), task_id, 'WorkflowStarted', now() - make_interval(hours => i, mins => 25), jsonb_build_object('message', 'QA seed workflow started', 'flow', flow), jsonb_build_object('qa_seed_batch', batch), ws, creator),
                (gen_random_uuid(), task_id, 'IterationStarted', now() - make_interval(hours => i, mins => 20), jsonb_build_object('iteration', 1, 'icp', icp), jsonb_build_object('qa_seed_batch', batch), ws, creator),
                (gen_random_uuid(), task_id, 'ToolCallStarted', now() - make_interval(hours => i, mins => 15), jsonb_build_object('tool', CASE WHEN i % 4 = 0 THEN 'agentarea/shell' WHEN i % 4 = 1 THEN 'agentarea/web' WHEN i % 4 = 2 THEN 'qa_seed_search' ELSE 'agentarea/skills' END), jsonb_build_object('qa_seed_batch', batch), ws, creator),
                (gen_random_uuid(), task_id, 'ToolCallCompleted', now() - make_interval(hours => i, mins => 10), jsonb_build_object('tool', 'qa_seed_tool', 'duration_ms', 200 + i), jsonb_build_object('qa_seed_batch', batch), ws, creator),
                (gen_random_uuid(), task_id, CASE WHEN st = 'failed' THEN 'WorkflowFailed' WHEN st = 'completed' THEN 'WorkflowCompleted' WHEN st = 'blocked' THEN 'HumanInputRequested' ELSE 'LLMCallCompleted' END,
                    now() - make_interval(hours => i, mins => 5),
                    jsonb_build_object('status', st, 'summary', 'QA seed event for ' || flow, 'artifact_kind', artifact_kind),
                    jsonb_build_object('qa_seed_batch', batch),
                    ws,
                    creator);

            IF st = 'completed' AND i % 2 = 0 THEN
                INSERT INTO artifact_events (
                    id, created_at, updated_at, workspace_id, created_by, path, action, actor_type, agent_id, task_id
                )
                VALUES (
                    gen_random_uuid(),
                    now() - make_interval(hours => i),
                    now() - make_interval(hours => i),
                    ws,
                    creator,
                    'artifacts/qa-seed/' || batch || '/task-' || i || '/result.' || artifact_kind,
                    'created',
                    'agent',
                    agent_id::text,
                    task_id::text
                );
            END IF;
        END LOOP;

        FOR i IN 1..20 LOOP
            agent_id := agent_ids[((i - 1) % array_length(agent_ids, 1)) + 1];
            INSERT INTO triggers (
                id, name, description, agent_id, trigger_type, is_active, task_parameters,
                conditions, failure_threshold, consecutive_failures, last_execution_at,
                cron_expression, timezone, webhook_id, allowed_methods, webhook_type,
                validation_rules, webhook_config, event_types,
                workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                'QA Seed Trigger ' || lpad(i::text, 2, '0') || ' ' || batch,
                'Synthetic trigger for cron/webhook automation testing.',
                agent_id,
                CASE WHEN i % 3 = 0 THEN 'webhook' WHEN i % 5 = 0 THEN 'polling' ELSE 'cron' END,
                i % 4 <> 0,
                json_build_object('qa_seed', true, 'flow', flows[((i - 1) % array_length(flows, 1)) + 1]),
                json_build_object('min_priority', CASE WHEN i % 2 = 0 THEN 'medium' ELSE 'low' END),
                5,
                i % 3,
                now() - make_interval(hours => i),
                CASE WHEN i % 3 <> 0 THEN (i % 60)::text || ' */' || ((i % 6) + 1)::text || ' * * *' ELSE NULL END,
                'Europe/Moscow',
                CASE WHEN i % 3 = 0 THEN 'qa-seed-webhook-' || batch || '-' || i ELSE NULL END,
                CASE WHEN i % 3 = 0 THEN json_build_array('POST', 'PUT') ELSE NULL END,
                CASE WHEN i % 3 = 0 THEN CASE WHEN i % 2 = 0 THEN 'github' ELSE 'generic' END ELSE NULL END,
                json_build_object('signature_required', i % 2 = 0),
                json_build_object('source', 'qa-seed', 'batch', batch),
                json_build_array('task.created', 'artifact.created'),
                ws,
                creator,
                now() - make_interval(hours => i),
                now()
            )
            RETURNING id INTO trigger_id;
            trigger_ids := array_append(trigger_ids, trigger_id);
        END LOOP;

        FOR i IN 1..60 LOOP
            trigger_id := trigger_ids[((i - 1) % array_length(trigger_ids, 1)) + 1];
            task_id := task_ids[((i - 1) % array_length(task_ids, 1)) + 1];
            INSERT INTO trigger_executions (
                id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
                trigger_data, workflow_id, run_id, workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                trigger_id,
                now() - make_interval(mins => i * 7),
                CASE WHEN i % 10 = 0 THEN 'timeout' WHEN i % 7 = 0 THEN 'failed' WHEN i % 13 = 0 THEN 'cancelled' ELSE 'success' END,
                CASE WHEN i % 7 = 0 THEN NULL ELSE task_id END,
                120 + i * 17,
                CASE WHEN i % 7 = 0 THEN 'QA seed synthetic trigger execution failure' ELSE NULL END,
                json_build_object('qa_seed', true, 'payload_id', 'payload-' || i, 'batch', batch),
                'qa-seed-trigger-workflow-' || batch || '-' || i,
                gen_random_uuid()::text,
                ws,
                creator,
                now() - make_interval(mins => i * 7),
                now()
            );
        END LOOP;

        FOR i IN 1..18 LOOP
            INSERT INTO workspace_invitations (
                id, created_at, updated_at, workspace_id, email, token_hash, invited_by,
                status, expires_at, accepted_at, accepted_by_user_id
            )
            VALUES (
                gen_random_uuid(),
                now() - make_interval(days => i),
                now(),
                ws,
                'qa-seed-invite-' || i || '-' || left(ws, 8) || '@agentarea.dev',
                md5(ws || batch || i),
                creator,
                CASE WHEN i % 9 = 0 THEN 'revoked' WHEN i % 5 = 0 THEN 'accepted' ELSE 'pending' END,
                now() + make_interval(days => 14 - (i % 7)),
                CASE WHEN i % 5 = 0 THEN now() - make_interval(hours => i) ELSE NULL END,
                CASE WHEN i % 5 = 0 THEN gen_random_uuid()::text ELSE NULL END
            )
            RETURNING id INTO new_id;

            IF i % 5 = 0 THEN
                INSERT INTO workspace_memberships (id, workspace_id, user_id, invitation_id, created_at, updated_at)
                VALUES (
                    gen_random_uuid(),
                    ws,
                    'qa-seed-member-' || i || '-' || left(ws, 8),
                    new_id,
                    now() - make_interval(hours => i),
                    now()
                )
                ON CONFLICT DO NOTHING;
            END IF;
        END LOOP;

        FOR i IN 1..14 LOOP
            INSERT INTO policies (
                id, subject_type, subject_id, target, effect, params, condition, enabled,
                priority, workspace_id, created_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                CASE WHEN i % 3 = 0 THEN 'agent' WHEN i % 3 = 1 THEN 'workspace' ELSE 'skill' END,
                CASE WHEN i % 3 = 0 THEN agent_ids[((i - 1) % array_length(agent_ids, 1)) + 1]::text WHEN i % 3 = 2 THEN skill_ids[((i - 1) % array_length(skill_ids, 1)) + 1]::text ELSE ws END,
                CASE WHEN i % 4 = 0 THEN 'tool:agentarea/shell' WHEN i % 4 = 1 THEN 'model:openrouter' WHEN i % 4 = 2 THEN 'budget:daily' ELSE 'delegation:*' END,
                CASE WHEN i % 5 = 0 THEN 'deny' WHEN i % 3 = 0 THEN 'warn' ELSE 'allow' END,
                jsonb_build_object('limit', 100 + i * 10, 'qa_seed_batch', batch, 'phase', CASE WHEN i % 2 = 0 THEN 'pre_tool_call' ELSE 'pre_llm_call' END),
                CASE WHEN i % 4 = 0 THEN 'priority == "high"' ELSE NULL END,
                i % 6 <> 0,
                i,
                ws,
                creator,
                now() - make_interval(hours => i),
                now()
            );
        END LOOP;

        FOR i IN 1..8 LOOP
            INSERT INTO api_keys (
                id, workspace_id, created_by, name, token_hash, token_prefix, is_active,
                expires_at, access_count, last_accessed_at, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                ws,
                creator,
                'QA Seed API Key ' || i || ' ' || batch,
                md5('qa-seed-api-key-' || ws || batch || i),
                'qa_' || substr(md5(ws || batch || i), 1, 8),
                i % 5 <> 0,
                CASE WHEN i % 4 = 0 THEN now() + make_interval(days => 30) ELSE NULL END,
                i * 11,
                CASE WHEN i % 3 = 0 THEN NULL ELSE now() - make_interval(hours => i) END,
                now() - make_interval(days => i),
                now()
            );
        END LOOP;

        FOR i IN 1..10 LOOP
            INSERT INTO encrypted_secrets (
                id, workspace_id, secret_name, encrypted_value, created_by, updated_by, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(),
                ws,
                'QA_SEED_SECRET_' || i || '_' || batch,
                'encrypted:qa-seed-placeholder:' || md5(ws || batch || i),
                creator,
                creator,
                now() - make_interval(days => i),
                now()
            );
        END LOOP;

        FOR i IN 1..80 LOOP
            INSERT INTO audit_events (
                id, created_at, updated_at, actor_id, actor_type, workspace_id, source_ip,
                user_agent, request_id, action, resource_type, resource_id, changes, event_metadata
            )
            VALUES (
                gen_random_uuid(),
                now() - make_interval(mins => i * 9),
                now() - make_interval(mins => i * 9),
                creator,
                CASE WHEN i % 6 = 0 THEN 'agent' ELSE 'user' END,
                ws,
                ('10.66.0.' || ((i % 240) + 1))::inet,
                'QA Seed Browser/' || batch,
                'qa-seed-request-' || batch || '-' || i,
                CASE
                    WHEN i % 9 = 0 THEN 'trigger.create'
                    WHEN i % 8 = 0 THEN 'governance_policy.create'
                    WHEN i % 7 = 0 THEN 'mcp_instance.create'
                    WHEN i % 6 = 0 THEN 'skill.update'
                    WHEN i % 5 = 0 THEN 'task.create'
                    WHEN i % 4 = 0 THEN 'agent.update'
                    WHEN i % 3 = 0 THEN 'skill.create'
                    ELSE 'agent.create'
                END,
                CASE
                    WHEN i % 9 = 0 THEN 'trigger'
                    WHEN i % 8 = 0 THEN 'governance_policy'
                    WHEN i % 7 = 0 THEN 'mcp_instance'
                    WHEN i % 5 = 0 THEN 'task'
                    WHEN i % 3 = 0 THEN 'skill'
                    ELSE 'agent'
                END,
                CASE
                    WHEN i % 5 = 0 THEN task_ids[((i - 1) % array_length(task_ids, 1)) + 1]::text
                    WHEN i % 3 = 0 THEN skill_ids[((i - 1) % array_length(skill_ids, 1)) + 1]::text
                    ELSE agent_ids[((i - 1) % array_length(agent_ids, 1)) + 1]::text
                END,
                jsonb_build_object('qa_seed_batch', batch, 'field', 'status', 'before', 'draft', 'after', 'active'),
                jsonb_build_object('qa_seed', true, 'batch', batch)
            );
        END LOOP;

        RAISE NOTICE 'QA seed batch % inserted for workspace %: % skills, % agents, % projects, % tasks, % triggers',
            batch, ws, array_length(skill_ids, 1), array_length(agent_ids, 1), array_length(project_ids, 1), array_length(task_ids, 1), array_length(trigger_ids, 1);
    END LOOP;
END $$;
