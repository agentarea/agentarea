-- name: InsertCostLine :execrows
INSERT INTO cost_entries (
    id, workspace_id, created_by, event_id, category, task_id, agent_id, subject_type,
    subject_id, subject_name, call_ref, amount, currency, provider_cost_usd, source, evidence,
    occurred_at, payer, vendor_cost, vendor_currency, estimate, correlation_id, causation_id, quantity, unit, client_id
) VALUES (
    @id, @workspace_id, @created_by, @event_id, @category, @task_id, @agent_id, @subject_type,
    sqlc.narg(subject_id), sqlc.narg(subject_name), sqlc.narg(call_ref), sqlc.arg(amount)::text::numeric,
    sqlc.narg(currency), sqlc.narg(provider_cost_usd)::text::numeric, @source, sqlc.arg(evidence)::text::jsonb,
    @occurred_at, @payer, sqlc.narg(vendor_cost)::text::numeric, sqlc.narg(vendor_currency), @estimate,
    sqlc.narg(correlation_id), sqlc.narg(causation_id), sqlc.narg(quantity)::text::numeric, sqlc.narg(unit),
    sqlc.narg(client_id)::uuid
) ON CONFLICT (event_id, category) DO NOTHING;

-- name: SumSpendSince :one
SELECT COALESCE(sum(c.amount), 0)::text AS total FROM cost_entries c
WHERE c.workspace_id = @workspace_id AND c.occurred_at >= @since
  AND NOT EXISTS (SELECT 1 FROM cost_entries n WHERE n.supersedes_id = c.id)
  AND (c.currency = @currency OR c.currency IS NULL)
  AND (sqlc.narg(agent_id)::uuid IS NULL OR c.agent_id = sqlc.narg(agent_id)::uuid)
  AND (sqlc.narg(task_id)::uuid IS NULL OR c.task_id = sqlc.narg(task_id)::uuid)
  AND (sqlc.narg(category)::text IS NULL OR c.category = sqlc.narg(category)::text)
  AND (sqlc.narg(connection_id)::text IS NULL OR (c.subject_type = 'tool' AND c.subject_id = sqlc.narg(connection_id)::text))
  AND (sqlc.narg(tool)::text IS NULL OR c.subject_name = sqlc.narg(tool)::text)
  AND (sqlc.narg(client_id)::uuid IS NULL OR c.client_id = sqlc.narg(client_id)::uuid);
