-- name: InsightsSpendSince :one
SELECT COALESCE(sum(c.amount), 0)::text AS total FROM cost_entries c
WHERE c.workspace_id = @workspace_id AND c.occurred_at >= @since
  AND NOT EXISTS (SELECT 1 FROM cost_entries n WHERE n.supersedes_id = c.id)
  AND (c.currency = @currency OR c.currency IS NULL)
  AND (sqlc.narg(agent_id)::uuid IS NULL OR c.agent_id = sqlc.narg(agent_id)::uuid)
  AND (NOT @estimate_only::bool OR c.estimate);

-- name: InsightsSpendByCurrency :many
SELECT COALESCE(c.currency, '')::text AS currency, sum(c.amount)::text AS total FROM cost_entries c
WHERE c.workspace_id = @workspace_id AND c.occurred_at >= @since
  AND NOT EXISTS (SELECT 1 FROM cost_entries n WHERE n.supersedes_id = c.id)
GROUP BY c.currency;

-- name: InsightsSpendByDay :many
SELECT (c.occurred_at AT TIME ZONE 'UTC')::date::text AS day, sum(c.amount)::text AS total FROM cost_entries c
WHERE c.workspace_id = @workspace_id AND c.occurred_at >= @since
  AND NOT EXISTS (SELECT 1 FROM cost_entries n WHERE n.supersedes_id = c.id)
  AND (c.currency = @currency OR c.currency IS NULL)
  AND (sqlc.narg(agent_id)::uuid IS NULL OR c.agent_id = sqlc.narg(agent_id)::uuid)
GROUP BY 1;

-- name: InsightsTopAgents :many
SELECT c.agent_id::uuid AS agent_id, sum(c.amount)::text AS total FROM cost_entries c
WHERE c.workspace_id = @workspace_id AND c.occurred_at >= @since
  AND NOT EXISTS (SELECT 1 FROM cost_entries n WHERE n.supersedes_id = c.id)
  AND (c.currency = @currency OR c.currency IS NULL)
  AND c.agent_id IS NOT NULL
GROUP BY c.agent_id
ORDER BY sum(c.amount) DESC, c.agent_id
LIMIT @lim;

-- name: InsightsTasks :many
SELECT id, agent_id, status, description, error,
    COALESCE(CASE WHEN json_typeof(result) = 'object' THEN (result->'total_cost')::text END, '')::text AS total_cost,
    created_at, updated_at, started_at, completed_at, scheduled_at
FROM tasks
WHERE workspace_id = @workspace_id AND status = ANY(@statuses::text[])
  AND (sqlc.narg(agent_id)::uuid IS NULL OR agent_id = sqlc.narg(agent_id)::uuid)
  AND (sqlc.narg(ended_since)::timestamp IS NULL OR COALESCE(completed_at, updated_at) >= sqlc.narg(ended_since)::timestamp)
  AND (sqlc.narg(scheduled_until)::timestamptz IS NULL
       OR (scheduled_at IS NOT NULL AND scheduled_at <= sqlc.narg(scheduled_until)::timestamptz))
ORDER BY
    CASE WHEN @ord::text = 'scheduled' THEN scheduled_at END ASC,
    CASE @ord::text
        WHEN 'updated' THEN updated_at
        WHEN 'ended' THEN COALESCE(completed_at, updated_at)
        WHEN 'activity' THEN COALESCE(started_at, created_at)
        WHEN 'created' THEN created_at
    END DESC,
    id
LIMIT @lim;

-- name: InsightsAgentSummary :one
SELECT
    COALESCE(sum(CASE WHEN status = 'completed' AND COALESCE(started_at, created_at) >= @today::timestamp THEN 1 ELSE 0 END), 0)::bigint AS done_today,
    COALESCE(sum(CASE WHEN status = 'failed' AND COALESCE(started_at, created_at) >= @today::timestamp THEN 1 ELSE 0 END), 0)::bigint AS failed_today,
    max(COALESCE(started_at, created_at))::timestamp AS last_activity
FROM tasks
WHERE workspace_id = @workspace_id AND agent_id = @agent_id;

-- name: InsightsAgentDays :many
SELECT COALESCE(started_at, created_at)::date::text AS day,
    COALESCE(sum(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0)::bigint AS completed,
    COALESCE(sum(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)::bigint AS failed,
    COALESCE(sum(CASE WHEN status = ANY(@input_statuses::text[]) THEN 1 ELSE 0 END), 0)::bigint AS input_required
FROM tasks
WHERE workspace_id = @workspace_id AND agent_id = @agent_id
  AND COALESCE(started_at, created_at) >= @since::timestamp
GROUP BY 1
ORDER BY 1;
