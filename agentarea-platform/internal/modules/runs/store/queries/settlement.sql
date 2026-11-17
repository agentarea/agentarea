-- name: ClaimUnsettledLines :many
-- Lines of every workspace marked for settlement, superseded by none, due now
-- (CrossWorkspaceCostLines.claim_unsettled): retried every tick while young,
-- then about every tenth of their age as a power-of-two number of ticks, at
-- most max_seconds apart, and not claimed by a live claim or dead. Locked
-- SKIP LOCKED so workers share them.
SELECT c.id, c.workspace_id, c.created_by, c.event_id, c.category, c.task_id, c.agent_id, c.subject_type,
       c.subject_id, c.subject_name, c.call_ref, c.amount::text AS amount, c.currency,
       COALESCE(c.provider_cost_usd::text, '')::text AS provider_cost_usd, c.source, c.evidence::text AS evidence, c.supersedes_id,
       c.occurred_at, c.client_id, c.payer, COALESCE(c.quantity::text, '')::text AS quantity, c.unit, COALESCE(c.vendor_cost::text, '')::text AS vendor_cost,
       c.vendor_currency, c.estimate, c.correlation_id, c.causation_id
FROM cost_entries c
WHERE c.evidence ? 'settle'
  AND c.occurred_at >= @since
  AND NOT EXISTS (SELECT 1 FROM cost_entries n WHERE n.supersedes_id = c.id)
  AND NOT EXISTS (SELECT 1 FROM cost_settlement_claims k WHERE k.line_id = c.id
        AND (k.dead_at IS NOT NULL OR k.claimed_until > sqlc.arg(now)::timestamptz))
  AND floor(sqlc.arg(now_epoch)::float8 / least(
        power(2, floor(ln(greatest(extract(epoch FROM (sqlc.arg(now)::timestamptz - c.occurred_at))::float8 / (10 * sqlc.arg(tick_seconds)::float8), 1)) / ln(2))) * sqlc.arg(tick_seconds)::float8,
        sqlc.arg(max_seconds)::float8))
   <> floor((sqlc.arg(now_epoch)::float8 - sqlc.arg(tick_seconds)::float8) / least(
        power(2, floor(ln(greatest(extract(epoch FROM (sqlc.arg(now)::timestamptz - c.occurred_at))::float8 / (10 * sqlc.arg(tick_seconds)::float8), 1)) / ln(2))) * sqlc.arg(tick_seconds)::float8,
        sqlc.arg(max_seconds)::float8))
ORDER BY c.occurred_at
LIMIT @batch
FOR UPDATE OF c SKIP LOCKED;

-- name: InsertSettledLine :execrows
INSERT INTO cost_entries (
    id, workspace_id, created_by, event_id, category, task_id, agent_id, client_id, subject_type,
    subject_id, subject_name, call_ref, amount, currency, provider_cost_usd, source, evidence, supersedes_id,
    occurred_at, payer, vendor_cost, vendor_currency, estimate, correlation_id, causation_id, quantity, unit
) VALUES (
    @id, sqlc.arg(workspace_id)::text, @created_by, @event_id, @category, sqlc.narg(task_id)::uuid, @agent_id, @client_id, @subject_type,
    sqlc.narg(subject_id), sqlc.narg(subject_name), sqlc.narg(call_ref), sqlc.arg(amount)::text::numeric,
    sqlc.narg(currency), sqlc.narg(provider_cost_usd)::text::numeric, @source, sqlc.arg(evidence)::text::jsonb,
    @supersedes_id, @occurred_at, @payer, sqlc.narg(vendor_cost)::text::numeric, sqlc.narg(vendor_currency), @estimate,
    (SELECT t.correlation_id FROM tasks t WHERE t.id = sqlc.narg(task_id)::uuid AND t.workspace_id = sqlc.arg(workspace_id)::text),
    (SELECT t.causation_id FROM tasks t WHERE t.id = sqlc.narg(task_id)::uuid AND t.workspace_id = sqlc.arg(workspace_id)::text),
    sqlc.narg(quantity)::text::numeric, sqlc.narg(unit)
) ON CONFLICT (event_id, category) DO NOTHING;

-- name: SupersededLines :many
-- Which of the claimed lines a line committed since the claim's snapshot supersedes.
SELECT n.supersedes_id::uuid AS id FROM cost_entries n WHERE n.supersedes_id = ANY(@ids::uuid[]);

-- name: ClaimLines :many
-- Claims the lines for claimed_by until claimed_until. A line another worker
-- claimed meanwhile, or one dead, is not returned: the conflict check sees
-- committed claims whatever the statement's snapshot.
INSERT INTO cost_settlement_claims (line_id, claimed_by, claimed_until)
SELECT unnest(@ids::uuid[]), @claimed_by::uuid, @claimed_until::timestamptz
ON CONFLICT (line_id) DO UPDATE SET claimed_by = EXCLUDED.claimed_by, claimed_until = EXCLUDED.claimed_until
WHERE cost_settlement_claims.dead_at IS NULL AND cost_settlement_claims.claimed_until <= @now::timestamptz
RETURNING line_id;

-- name: ReleaseClaim :exec
DELETE FROM cost_settlement_claims WHERE line_id = @line_id AND claimed_by = @claimed_by::uuid;

-- name: DeferClaim :exec
UPDATE cost_settlement_claims SET claimed_by = NULL, attempts = cost_settlement_claims.attempts + 1,
    claimed_until = sqlc.arg(now)::timestamptz + make_interval(0, 0, 0, 0, 0, 0, least(sqlc.arg(tick_seconds)::float8 * power(2, cost_settlement_claims.attempts), sqlc.arg(max_seconds)::float8))
WHERE line_id = @line_id AND claimed_by = @claimed_by::uuid;

-- name: KillClaim :exec
UPDATE cost_settlement_claims SET claimed_by = NULL, dead_at = @now::timestamptz, dead_reason = @reason
WHERE line_id = @line_id AND claimed_by = @claimed_by::uuid;
