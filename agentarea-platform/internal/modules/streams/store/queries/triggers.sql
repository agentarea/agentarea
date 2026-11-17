-- name: InsertTrigger :one
INSERT INTO triggers (id, name, description, agent_id, trigger_type, is_active, task_parameters, conditions,
    failure_threshold, consecutive_failures, cron_expression, timezone, workspace_id, created_by,
    created_at, updated_at, session, batch, task_definition_id)
VALUES (@id, @name, @description, @agent_id, @trigger_type, @is_active, @task_parameters, @conditions,
    @failure_threshold, 0, @cron_expression, @timezone, @workspace_id, @created_by,
    @now, @now, @session, @batch, @task_definition_id)
RETURNING id;

-- name: GetTrigger :one
SELECT * FROM triggers WHERE workspace_id = @workspace_id AND id = @id;

-- name: GetTriggerAnyWorkspace :one
SELECT * FROM triggers WHERE id = @id;

-- name: ListCronTriggers :many
SELECT id, workspace_id, cron_expression, timezone, is_active FROM triggers
WHERE trigger_type = 'cron' ORDER BY id;

-- name: ListTriggers :many
SELECT * FROM triggers
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid)
  AND (sqlc.narg(trigger_type)::varchar IS NULL OR trigger_type = sqlc.narg(trigger_type)::varchar)
  AND (NOT @active_only::bool OR is_active)
ORDER BY created_at, id
LIMIT @lim;

-- name: UpdateTriggerRow :execrows
UPDATE triggers SET
    name = @name, description = @description, agent_id = @agent_id, is_active = @is_active,
    task_parameters = @task_parameters, conditions = @conditions, failure_threshold = @failure_threshold,
    cron_expression = @cron_expression, timezone = @timezone, session = @session, batch = @batch,
    task_definition_id = @task_definition_id, needs_new_owner_at = @needs_new_owner_at, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeleteTrigger :execrows
DELETE FROM triggers WHERE workspace_id = @workspace_id AND id = @id;

-- name: InsertTriggerExecution :one
INSERT INTO trigger_executions (id, trigger_id, executed_at, status, task_id, execution_time_ms, error_message,
    trigger_data, workspace_id, created_by, created_at, updated_at, fired_by)
SELECT @id, t.id, @executed_at, @status, sqlc.narg(task_id)::uuid, @execution_time_ms, sqlc.narg(error_message)::text,
    @trigger_data, t.workspace_id, t.created_by, @executed_at, @executed_at, sqlc.narg(fired_by)::varchar
FROM triggers t WHERE t.id = @trigger_id
RETURNING id, executed_at;

-- name: MarkTriggerExecuted :execrows
UPDATE triggers SET
    last_execution_at = @executed_at,
    consecutive_failures = CASE WHEN @reset::bool THEN 0 ELSE consecutive_failures + 1 END
WHERE id = @id;

-- name: ListTriggerExecutions :many
SELECT * FROM trigger_executions
WHERE trigger_id = @trigger_id AND workspace_id = @workspace_id
ORDER BY executed_at DESC, id DESC
LIMIT @lim;

-- name: InsertTriggerSubscription :exec
INSERT INTO stream_subscriptions (id, stream_id, workspace_id, kind, trigger_id, filter, output_stream_ids,
    status, started_at, created_at, updated_at, created_by, code)
VALUES (@id, @stream_id, @workspace_id, 'trigger', @trigger_id, @filter, '[]'::json, @status, @started_at,
    @created_at, @created_at, @created_by, NULL);

-- name: GetTriggerBinding :one
SELECT s.stream_id, s.filter,
    (SELECT e.received_at FROM stream_events e WHERE e.stream_id = s.stream_id
     ORDER BY e.sequence DESC LIMIT 1)::timestamp AS last_event_at
FROM stream_subscriptions s
WHERE s.trigger_id = @trigger_id AND s.kind = 'trigger';

-- name: UpdateTriggerSubscriptionFilter :execrows
UPDATE stream_subscriptions SET filter = @filter, stream_id = @stream_id, status = @status
WHERE trigger_id = @trigger_id AND kind = 'trigger';

-- name: SetTriggerSubscriptionStatus :execrows
UPDATE stream_subscriptions SET status = @status WHERE trigger_id = @trigger_id AND kind = 'trigger';

-- name: CountTriggersByTaskDefinition :one
SELECT count(*)::bigint FROM triggers WHERE workspace_id = @workspace_id AND task_definition_id = @task_definition_id;

-- name: StreamExists :one
SELECT EXISTS (SELECT 1 FROM streams WHERE workspace_id = @workspace_id AND id = @id);

-- name: SetTriggerActive :execrows
UPDATE triggers SET is_active = @is_active,
    needs_new_owner_at = CASE WHEN @is_active::bool THEN NULL ELSE needs_new_owner_at END,
    consecutive_failures = CASE WHEN @is_active::bool THEN 0 ELSE consecutive_failures END,
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;
