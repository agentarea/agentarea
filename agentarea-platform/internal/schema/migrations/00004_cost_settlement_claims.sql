-- A settlement worker's claim on a ledger line waiting on settlement: held
-- while the worker calls out with no transaction open, expiring if it dies,
-- pushed back after a failure, and dead for a line no retry can settle. The
-- ledger itself stays append-only.

-- +goose Up
CREATE TABLE public.cost_settlement_claims (
    line_id uuid NOT NULL PRIMARY KEY,
    claimed_by uuid,
    claimed_until timestamp with time zone NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    dead_at timestamp with time zone,
    dead_reason text
);

-- +goose Down
DROP TABLE public.cost_settlement_claims;
