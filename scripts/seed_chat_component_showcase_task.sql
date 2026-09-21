\set ON_ERROR_STOP on

-- One scoped, synthetic task for visually checking the production chat renderers.
-- Required psql variables:
--   workspace_id, agent_id, creator_id
-- Optional:
--   apply=true commits; omitted/false runs the full seed as a rolled-back preview.

\if :{?workspace_id}
\else
  \echo 'Missing -v workspace_id=<uuid>'
  \quit
\endif
\if :{?agent_id}
\else
  \echo 'Missing -v agent_id=<uuid>'
  \quit
\endif
\if :{?creator_id}
\else
  \echo 'Missing -v creator_id=<user-id>'
  \quit
\endif
\if :{?apply}
\else
  \set apply false
\endif

BEGIN;

CREATE TEMP TABLE chat_showcase_seed AS
SELECT
    :'workspace_id'::text AS workspace_id,
    :'agent_id'::uuid AS agent_id,
    :'creator_id'::text AS creator_id,
    gen_random_uuid() AS task_id,
    clock_timestamp() - interval '2 seconds' AS base_time,
    $markdown$
## Проверка списка лидов

Это демонстрационные данные. Три лида отсортированы по соответствию профилю клиента.

| Компания | Балл | Следующий шаг |
| --- | ---: | --- |
| Север Софт | 92 | Назначить встречу |
| Маяк Данные | 84 | Уточнить бюджет |
| Вектор Лаб | 76 | Отправить материалы |

- Сначала связаться с «Север Софт».
- Для «Маяк Данные» проверить срок закупки.

```ts
type LeadScore = { company: string; score: number };
const priority = leads.filter((lead) => lead.score >= 80);
```

[Открыть галерею всех компонентов чата](/tasks/showcase)
$markdown$::text AS final_markdown;

DO $validate$
DECLARE
    seed record;
BEGIN
    SELECT * INTO seed FROM chat_showcase_seed;

    IF NOT EXISTS (
        SELECT 1
        FROM workspaces
        WHERE id::text = seed.workspace_id
    ) THEN
        RAISE EXCEPTION 'Workspace % does not exist', seed.workspace_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM agents
        WHERE id = seed.agent_id
          AND workspace_id = seed.workspace_id
          AND created_by = seed.creator_id
          AND name = 'BizDev — Score'
    ) THEN
        RAISE EXCEPTION 'Agent % is not creator-owned BizDev — Score in workspace %', seed.agent_id, seed.workspace_id;
    END IF;
END
$validate$;

INSERT INTO tasks (
    id,
    agent_id,
    description,
    parameters,
    status,
    result,
    error,
    started_at,
    completed_at,
    execution_id,
    task_metadata,
    project_id,
    workspace_id,
    created_by,
    created_at,
    updated_at
)
SELECT
    task_id,
    agent_id,
    '[Демо] Проверка списка лидов',
    json_build_object(
        'demo', true,
        'fixture', 'chat-component-showcase-v1',
        'external_execution', false
    ),
    'completed',
    json_build_object(
        'response', final_markdown,
        'final_response', final_markdown,
        'total_cost', '0.00',
        'showcase_url', '/tasks/showcase'
    ),
    NULL,
    (base_time AT TIME ZONE 'UTC'),
    ((base_time + interval '1500 milliseconds') AT TIME ZONE 'UTC'),
    'demo-chat-components-' || task_id::text,
    json_build_object(
        'demo', true,
        'fixture', 'chat-component-showcase-v1',
        'source', 'scripts/seed_chat_component_showcase_task.sql',
        'showcase_url', '/tasks/showcase'
    ),
    NULL,
    workspace_id,
    creator_id,
    (base_time AT TIME ZONE 'UTC'),
    (clock_timestamp() AT TIME ZONE 'UTC')
FROM chat_showcase_seed;

WITH event_rows(sequence, event_type, data) AS (
    VALUES
        (1, 'task.started', jsonb_build_object(
            'message', 'Запущена демонстрационная проверка лидов.',
            'execution_id', 'demo-chat-components'
        )),
        (2, 'llm.call.completed', jsonb_build_object(
            'execution_id', 'demo-chat-components',
            'iteration', 0,
            'content', 'Проверяю **три демонстрационных лида**. Реальные инструменты и модели не запускаются.',
            'cost', '0.00'
        )),
        (3, 'tool.call', jsonb_build_object(
            'tool_call_id', 'demo-tool-pending',
            'tool_name', 'demo_pending_state',
            'arguments', jsonb_build_object('demo_data', true, 'step', 'Ожидание ответа')
        )),
        (4, 'tool.call', jsonb_build_object(
            'tool_call_id', 'demo-tool-success',
            'tool_name', 'run_command',
            'arguments', jsonb_build_object('command', 'python3 score_leads.py --demo')
        )),
        (5, 'tool.result', jsonb_build_object(
            'tool_call_id', 'demo-tool-success',
            'tool_name', 'run_command',
            'arguments', jsonb_build_object('command', 'python3 score_leads.py --demo'),
            'result', 'Север Софт — 92 — назначить встречу\nМаяк Данные — 84 — уточнить бюджет\nВектор Лаб — 76 — отправить материалы',
            'success', true,
            'duration_ms', 184,
            'exit_code', 0
        )),
        (6, 'tool.result', jsonb_build_object(
            'tool_call_id', 'demo-tool-failed',
            'tool_name', 'demo_validation',
            'arguments', jsonb_build_object('demo_data', true, 'scenario', 'Ошибка'),
            'error', 'Демонстрационная ошибка: не заполнена отрасль.',
            'success', false,
            'duration_ms', 311,
            'exit_code', 1
        )),
        (7, 'tool.result', jsonb_build_object(
            'tool_call_id', 'demo-tool-omitted',
            'tool_name', 'demo_omitted_details',
            'arguments', jsonb_build_object('payload', '[nested value omitted from event log]'),
            'result', '[omitted from event log: 2048 units]',
            'execution_time', '[redacted]',
            'success', true
        )),
        (8, 'input.request', jsonb_build_object(
            'input_request_id', 'demo-input-resolved',
            'question', 'Параметры демо-проверки',
            'questions', jsonb_build_array(
                jsonb_build_object('id', 'segment', 'question', 'Сегмент', 'type', 'text', 'required', true),
                jsonb_build_object('id', 'threshold', 'question', 'Минимальный балл', 'type', 'number', 'required', true)
            )
        )),
        (9, 'input.response', jsonb_build_object(
            'input_request_id', 'demo-input-resolved',
            'question', 'Параметры демо-проверки',
            'answers', jsonb_build_object('segment', 'B2B SaaS', 'threshold', 70),
            'message', 'Параметры демо сохранены.'
        )),
        (10, 'approval.request', jsonb_build_object(
            'escalation_id', 'demo-approval-resolved',
            'tool_call_id', 'demo-approval-tool',
            'tool_name', 'demo_review',
            'reason', 'Демо-согласование результата'
        )),
        (11, 'approval.response', jsonb_build_object(
            'escalation_id', 'demo-approval-resolved',
            'tool_call_id', 'demo-approval-tool',
            'tool_name', 'demo_review',
            'reason', 'Демо-согласование результата',
            'approved', true,
            'message', 'Демо-согласование завершено.'
        )),
        (12, 'artifact.created', jsonb_build_object(
            'artifact_id', 'demo-artifact-report',
            'name', 'лиды-демо.csv',
            'mime_type', 'text/csv'
        )),
        (13, 'artifact.created', jsonb_build_object(
            'artifact_id', 'demo-artifact-image',
            'name', 'краткий-отчёт.md',
            'mime_type', 'text/markdown'
        )),
        (14, 'a2ui.create', jsonb_build_object(
            'surface_id', 'demo-a2ui-surface',
            'catalog_id', 'https://a2ui.org/specification/v0_9/basic_catalog.json',
            'send_data_model', false
        )),
        (15, 'a2ui.update.components', $a2ui$
        {
          "surface_id": "demo-a2ui-surface",
          "components": [
            {"id":"root","component":"Column","children":["heading","summary-card","tabs","catalog-link"]},
            {"id":"heading","component":"Text","variant":"h2","text":"Результат проверки"},
            {"id":"summary-card","component":"Card","child":"summary-column"},
            {"id":"summary-column","component":"Column","children":["summary","status-row","divider","items"]},
            {"id":"summary","component":"Text","text":"3 демонстрационных лида · средний балл 84"},
            {"id":"status-row","component":"Row","align":"center","children":["status-icon","status"]},
            {"id":"status-icon","component":"Icon","name":"check"},
            {"id":"status","component":"Text","variant":"caption","text":"Демо-данные"},
            {"id":"divider","component":"Divider","axis":"horizontal"},
            {"id":"items","component":"List","direction":"horizontal","children":["item-one","item-two","item-three"]},
            {"id":"item-one","component":"Text","text":"Север Софт · 92"},
            {"id":"item-two","component":"Text","text":"Маяк Данные · 84"},
            {"id":"item-three","component":"Text","text":"Вектор Лаб · 76"},
            {"id":"tabs","component":"Tabs","tabs":[{"title":"Сводка","child":"tab-one"},{"title":"Детали","child":"tab-two"}]},
            {"id":"tab-one","component":"Text","text":"Лучший кандидат: Север Софт. Следующий шаг — назначить встречу."},
            {"id":"tab-two","component":"Text","text":"Оценка основана на демонстрационных размере команды, отрасли и сроке закупки."},
            {"id":"catalog-link","component":"Text","variant":"caption","text":"Все компоненты: /tasks/showcase"}
          ]
        }
        $a2ui$::jsonb),
        (16, 'a2ui.update.data', jsonb_build_object(
            'surface_id', 'demo-a2ui-surface',
            'path', '/',
            'value', jsonb_build_object('demo', true, 'lead_count', 3, 'average_score', 84)
        )),
        (17, 'llm.call.completed', jsonb_build_object(
            'execution_id', 'demo-chat-components',
            'iteration', 1,
            'content', (SELECT final_markdown FROM chat_showcase_seed),
            'cost', '0.00'
        )),
        (18, 'task.completed', jsonb_build_object(
            'message', 'Демонстрационная проверка лидов завершена.',
            'result', (SELECT final_markdown FROM chat_showcase_seed),
            'final_response', (SELECT final_markdown FROM chat_showcase_seed),
            'status', 'completed'
        ))
)
INSERT INTO task_events (
    id,
    task_id,
    event_type,
    timestamp,
    data,
    event_metadata,
    workspace_id,
    created_by
)
SELECT
    gen_random_uuid(),
    seed.task_id,
    event_rows.event_type,
    seed.base_time + event_rows.sequence * interval '80 milliseconds',
    event_rows.data,
    jsonb_build_object(
        'demo', true,
        'fixture', 'chat-component-showcase-v1',
        'sequence', event_rows.sequence
    ),
    seed.workspace_id,
    seed.creator_id
FROM event_rows
CROSS JOIN chat_showcase_seed seed
ORDER BY event_rows.sequence;

SELECT
    task_id,
    '/tasks/' || task_id::text AS task_url,
    workspace_id,
    agent_id,
    creator_id,
    base_time AS created_at,
    18 AS event_count,
    CASE WHEN :'apply'::boolean THEN 'will commit' ELSE 'preview only; will roll back' END AS outcome
FROM chat_showcase_seed;

\if :apply
  COMMIT;
  \echo 'Applied one chat component showcase task.'
\else
  ROLLBACK;
  \echo 'Preview complete; no rows were written. Re-run with -v apply=true to commit.'
\endif
