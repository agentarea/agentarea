-- name: WalletByAgent :one
SELECT id, workspace_id, created_by, agent_id, wallet_type,
    CAST(COALESCE(x402_config::text, 'null') AS text) AS x402_json, CAST(COALESCE(mpp_config::text, 'null') AS text) AS mpp_json,
    credentials_secret_id, service_budget_usd::text AS service_budget_usd,
    service_budget_period, status, created_at, updated_at
FROM agent_wallets WHERE workspace_id = @workspace_id AND agent_id = @agent_id;

-- LockWalletByAgent is WalletByAgent holding the row until the transaction
-- ends: reservations on one wallet run one at a time.
-- name: LockWalletByAgent :one
SELECT id, workspace_id, created_by, agent_id, wallet_type,
    CAST(COALESCE(x402_config::text, 'null') AS text) AS x402_json, CAST(COALESCE(mpp_config::text, 'null') AS text) AS mpp_json,
    credentials_secret_id, service_budget_usd::text AS service_budget_usd,
    service_budget_period, status, created_at, updated_at
FROM agent_wallets WHERE workspace_id = @workspace_id AND agent_id = @agent_id
FOR UPDATE;

-- name: CreateWallet :one
INSERT INTO agent_wallets (id, created_at, updated_at, workspace_id, created_by, agent_id, wallet_type,
    x402_config, mpp_config, credentials_secret_id, service_budget_usd, service_budget_period, status)
VALUES (@id, @now, @now, @workspace_id, @created_by, @agent_id, @wallet_type,
    CAST(sqlc.narg(x402_config) AS text)::json, CAST(sqlc.narg(mpp_config) AS text)::json, sqlc.narg(credentials_secret_id)::varchar,
    CAST(@service_budget_usd AS text)::numeric, @service_budget_period, 'active')
RETURNING id, workspace_id, created_by, agent_id, wallet_type,
    CAST(COALESCE(x402_config::text, 'null') AS text) AS x402_json, CAST(COALESCE(mpp_config::text, 'null') AS text) AS mpp_json,
    credentials_secret_id, service_budget_usd::text AS service_budget_usd,
    service_budget_period, status, created_at, updated_at;

-- UpdateWallet moves updated_at only when a written value differs, as SQLAlchemy
-- emits no UPDATE for an unchanged row.
-- name: UpdateWallet :one
UPDATE agent_wallets SET
    wallet_type = CASE WHEN @set_type::bool THEN @wallet_type::varchar ELSE wallet_type END,
    x402_config = CASE WHEN @set_x402::bool THEN CAST(sqlc.narg(x402_config) AS text)::json ELSE x402_config END,
    mpp_config = CASE WHEN @set_mpp::bool THEN CAST(sqlc.narg(mpp_config) AS text)::json ELSE mpp_config END,
    credentials_secret_id = CASE WHEN @set_credentials::bool THEN sqlc.narg(credentials_secret_id)::varchar ELSE credentials_secret_id END,
    service_budget_usd = CASE WHEN @set_budget::bool THEN CAST(@service_budget_usd AS text)::numeric ELSE service_budget_usd END,
    service_budget_period = CASE WHEN @set_period::bool THEN @service_budget_period::varchar ELSE service_budget_period END,
    status = CASE WHEN @set_status::bool THEN @status::varchar ELSE status END,
    updated_at = CASE WHEN
        (@set_type::bool AND wallet_type IS DISTINCT FROM @wallet_type::varchar)
        OR (@set_x402::bool AND x402_config::jsonb IS DISTINCT FROM CAST(sqlc.narg(x402_config) AS text)::jsonb)
        OR (@set_mpp::bool AND mpp_config::jsonb IS DISTINCT FROM CAST(sqlc.narg(mpp_config) AS text)::jsonb)
        OR (@set_credentials::bool AND credentials_secret_id IS DISTINCT FROM sqlc.narg(credentials_secret_id)::varchar)
        OR (@set_budget::bool AND service_budget_usd IS DISTINCT FROM CAST(@service_budget_usd AS text)::numeric)
        OR (@set_period::bool AND service_budget_period IS DISTINCT FROM @service_budget_period::varchar)
        OR (@set_status::bool AND status IS DISTINCT FROM @status::varchar)
        THEN @now ELSE updated_at END
WHERE workspace_id = @workspace_id AND id = @id
RETURNING id, workspace_id, created_by, agent_id, wallet_type,
    CAST(COALESCE(x402_config::text, 'null') AS text) AS x402_json, CAST(COALESCE(mpp_config::text, 'null') AS text) AS mpp_json,
    credentials_secret_id, service_budget_usd::text AS service_budget_usd,
    service_budget_period, status, created_at, updated_at;

-- name: DeleteWallet :execrows
DELETE FROM agent_wallets WHERE workspace_id = @workspace_id AND id = @id;

-- ExhaustedWallets: active wallets with a daily or monthly budget whose settled
-- spend and live pending reservations since the period start reached it
-- (WalletRepository.list_budget_exhausted).
-- name: ExhaustedWallets :many
SELECT w.id, w.workspace_id, w.created_by, w.agent_id, w.wallet_type,
    CAST(COALESCE(w.x402_config::text, 'null') AS text) AS x402_json, CAST(COALESCE(w.mpp_config::text, 'null') AS text) AS mpp_json,
    w.credentials_secret_id, w.service_budget_usd::text AS service_budget_usd,
    w.service_budget_period, w.status, w.created_at, w.updated_at
FROM agent_wallets w
WHERE w.workspace_id = @workspace_id
  AND w.status = 'active'
  AND w.service_budget_usd > 0
  AND w.service_budget_period IN ('daily', 'monthly')
  AND COALESCE((
        SELECT SUM(p.amount_usd) FROM payment_records p
        WHERE p.workspace_id = w.workspace_id
          AND p.agent_id = w.agent_id::text
          AND (p.status = 'completed' OR (p.status = 'pending' AND p.updated_at >= @held_since::timestamp))
          AND p.created_at >= CASE w.service_budget_period WHEN 'daily' THEN @daily_start::timestamp ELSE @monthly_start::timestamp END
    ), 0) >= w.service_budget_usd
ORDER BY w.created_at, w.id;
