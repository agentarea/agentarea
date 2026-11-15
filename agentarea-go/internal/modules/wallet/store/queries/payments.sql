-- name: InsertPayment :one
INSERT INTO payment_records (id, created_at, updated_at, workspace_id, created_by, wallet_id, agent_id, execution_id,
    protocol, amount_usd, recipient, tx_hash, tool_name, tool_call_id, idempotency_key, status, error_message, protocol_metadata)
VALUES (@id, @now, @now, @workspace_id, @created_by, @wallet_id, @agent_id, @execution_id,
    @protocol, CAST(@amount_usd AS text)::numeric, @recipient, NULL, @tool_name, @tool_call_id, @idempotency_key,
    @status, NULL, CAST(sqlc.narg(protocol_metadata) AS text)::json)
ON CONFLICT (workspace_id, idempotency_key) WHERE status = 'completed' DO NOTHING
RETURNING id, wallet_id, agent_id, execution_id, protocol, amount_usd::text AS amount_usd, recipient, tx_hash,
    tool_name, tool_call_id, idempotency_key, status, error_message, CAST(COALESCE(protocol_metadata::text, 'null') AS text) AS protocol_metadata, created_at;

-- name: SettledPaymentByKey :one
SELECT id, wallet_id, agent_id, execution_id, protocol, amount_usd::text AS amount_usd, recipient, tx_hash,
    tool_name, tool_call_id, idempotency_key, status, error_message, CAST(COALESCE(protocol_metadata::text, 'null') AS text) AS protocol_metadata, created_at
FROM payment_records
WHERE workspace_id = @workspace_id AND idempotency_key = @idempotency_key AND status = 'completed';

-- PendingPaymentByKey is the reservation still holding under the idempotency
-- key: pending and touched since held_since, or pending and signed at any age
-- (its payment may still settle), a signed one first.
-- name: PendingPaymentByKey :one
SELECT id, wallet_id, agent_id, execution_id, protocol, amount_usd::text AS amount_usd, recipient, tx_hash,
    tool_name, tool_call_id, idempotency_key, status, error_message, CAST(COALESCE(protocol_metadata::text, 'null') AS text) AS protocol_metadata, created_at,
    CAST(COALESCE(signed_headers::text, '') AS text) AS signed_headers
FROM payment_records
WHERE workspace_id = @workspace_id AND idempotency_key = @idempotency_key AND status = 'pending'
  AND (updated_at >= @held_since::timestamp OR signed_headers IS NOT NULL)
ORDER BY signed_headers IS NULL, created_at, id
LIMIT 1;

-- name: LockPendingPayment :one
SELECT id, wallet_id, agent_id, execution_id, protocol, amount_usd::text AS amount_usd, recipient, tx_hash,
    tool_name, tool_call_id, idempotency_key, status, error_message, CAST(COALESCE(protocol_metadata::text, 'null') AS text) AS protocol_metadata, created_at,
    CAST(COALESCE(signed_headers::text, '') AS text) AS signed_headers
FROM payment_records
WHERE workspace_id = @workspace_id AND id = @id AND status = 'pending'
FOR UPDATE;

-- name: SetPaymentSigned :exec
UPDATE payment_records SET signed_headers = CAST(@signed_headers AS text)::json
WHERE workspace_id = @workspace_id AND id = @id;

-- SettlePayment ends a pending reservation; a completion whose key settled
-- meanwhile violates the settled-key index.
-- name: SettlePayment :one
UPDATE payment_records SET
    status = @status,
    tx_hash = sqlc.narg(tx_hash)::varchar,
    error_message = sqlc.narg(error_message)::varchar,
    protocol_metadata = COALESCE(CAST(sqlc.narg(protocol_metadata) AS text)::json, protocol_metadata),
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id AND status = 'pending'
RETURNING id, wallet_id, agent_id, execution_id, protocol, amount_usd::text AS amount_usd, recipient, tx_hash,
    tool_name, tool_call_id, idempotency_key, status, error_message, CAST(COALESCE(protocol_metadata::text, 'null') AS text) AS protocol_metadata, created_at;

-- The sums count settled payments, and pending reservations made since
-- held_since when it is set: an older hold belongs to a run that died.
-- name: SumPaymentsByExecution :one
SELECT COALESCE(SUM(amount_usd), 0::numeric)::text AS total FROM payment_records
WHERE workspace_id = @workspace_id AND agent_id = @agent_id AND execution_id = @execution_id
  AND (status = 'completed' OR (status = 'pending' AND updated_at >= sqlc.narg(held_since)::timestamp));

-- name: SumPaymentsSince :one
SELECT COALESCE(SUM(amount_usd), 0::numeric)::text AS total FROM payment_records
WHERE workspace_id = @workspace_id AND agent_id = @agent_id
  AND (status = 'completed' OR (status = 'pending' AND updated_at >= sqlc.narg(held_since)::timestamp))
  AND (sqlc.narg(since)::timestamp IS NULL OR created_at >= sqlc.narg(since)::timestamp);

-- ListPayments is newest first; Python had no ORDER BY.
-- name: ListPayments :many
SELECT id, wallet_id, agent_id, execution_id, protocol, amount_usd::text AS amount_usd, recipient, tx_hash,
    tool_name, tool_call_id, idempotency_key, status, error_message, CAST(COALESCE(protocol_metadata::text, 'null') AS text) AS protocol_metadata, created_at
FROM payment_records
WHERE workspace_id = @workspace_id AND agent_id = @agent_id
  AND (sqlc.narg(protocol)::varchar IS NULL OR protocol = sqlc.narg(protocol)::varchar)
  AND (sqlc.narg(status)::varchar IS NULL OR status = sqlc.narg(status)::varchar)
  AND (sqlc.narg(from_date)::timestamp IS NULL OR created_at >= sqlc.narg(from_date)::timestamp)
  AND (sqlc.narg(to_date)::timestamp IS NULL OR created_at <= sqlc.narg(to_date)::timestamp)
ORDER BY created_at DESC, id DESC
LIMIT @lim OFFSET @off;

-- name: CountPayments :one
SELECT count(*) FROM payment_records
WHERE workspace_id = @workspace_id AND agent_id = @agent_id
  AND (sqlc.narg(protocol)::varchar IS NULL OR protocol = sqlc.narg(protocol)::varchar)
  AND (sqlc.narg(status)::varchar IS NULL OR status = sqlc.narg(status)::varchar)
  AND (sqlc.narg(from_date)::timestamp IS NULL OR created_at >= sqlc.narg(from_date)::timestamp)
  AND (sqlc.narg(to_date)::timestamp IS NULL OR created_at <= sqlc.narg(to_date)::timestamp);
