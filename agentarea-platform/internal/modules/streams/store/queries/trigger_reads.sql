-- name: TriggerExecutionsPage :many
SELECT * FROM trigger_executions
WHERE workspace_id = @workspace_id AND trigger_id = @trigger_id
  AND (sqlc.narg(status)::varchar IS NULL OR status = sqlc.narg(status)::varchar)
  AND (sqlc.narg(start_time)::timestamp IS NULL OR executed_at >= sqlc.narg(start_time)::timestamp)
  AND (sqlc.narg(end_time)::timestamp IS NULL OR executed_at <= sqlc.narg(end_time)::timestamp)
ORDER BY executed_at DESC, id DESC
LIMIT @lim OFFSET @off;

-- name: CountTriggerExecutions :one
SELECT count(*)::bigint FROM trigger_executions
WHERE workspace_id = @workspace_id AND trigger_id = @trigger_id
  AND (sqlc.narg(status)::varchar IS NULL OR status = sqlc.narg(status)::varchar)
  AND (sqlc.narg(start_time)::timestamp IS NULL OR executed_at >= sqlc.narg(start_time)::timestamp)
  AND (sqlc.narg(end_time)::timestamp IS NULL OR executed_at <= sqlc.narg(end_time)::timestamp);

-- name: TriggerExecutionMetrics :one
SELECT count(*)::bigint AS total,
    count(*) FILTER (WHERE status = 'success')::bigint AS successful,
    count(*) FILTER (WHERE status = 'failed')::bigint AS failed,
    count(*) FILTER (WHERE status = 'timeout')::bigint AS timed_out,
    count(*) FILTER (WHERE status = 'skipped')::bigint AS skipped,
    coalesce(avg(execution_time_ms), 0)::float8 AS avg_ms,
    coalesce(min(execution_time_ms), 0)::int AS min_ms,
    coalesce(max(execution_time_ms), 0)::int AS max_ms
FROM trigger_executions
WHERE workspace_id = @workspace_id AND trigger_id = @trigger_id
  AND (sqlc.narg(since)::timestamp IS NULL OR executed_at >= sqlc.narg(since)::timestamp);

-- name: TriggerExecutionTasks :many
SELECT task_id::uuid AS task_id FROM trigger_executions
WHERE workspace_id = @workspace_id AND trigger_id = @trigger_id AND task_id IS NOT NULL
  AND (sqlc.narg(since)::timestamp IS NULL OR executed_at >= sqlc.narg(since)::timestamp);

-- name: TriggerExecutionTimeline :many
SELECT (to_timestamp(floor(extract(epoch FROM executed_at) / @bucket_seconds::int) * @bucket_seconds::int)
        AT TIME ZONE 'UTC')::timestamp AS time_bucket,
    count(*)::bigint AS total,
    count(*) FILTER (WHERE status = 'success')::bigint AS successful,
    count(*) FILTER (WHERE status = 'failed')::bigint AS failed,
    count(*) FILTER (WHERE status = 'timeout')::bigint AS timed_out
FROM trigger_executions
WHERE workspace_id = @workspace_id AND trigger_id = @trigger_id AND executed_at >= @since::timestamp
GROUP BY 1
ORDER BY 1;

-- name: CountWorkspaceTriggers :one
SELECT count(*)::bigint FROM triggers WHERE workspace_id = @workspace_id;

-- name: CountActiveCronTriggers :one
SELECT count(*)::bigint FROM triggers WHERE workspace_id = @workspace_id AND trigger_type = 'cron' AND is_active;

-- name: CountFiringsSince :one
SELECT count(*)::bigint AS total,
    count(*) FILTER (WHERE status IN ('failed', 'timeout'))::bigint AS failures
FROM trigger_executions
WHERE workspace_id = @workspace_id AND trigger_id IS NOT NULL AND executed_at >= @since::timestamp;
