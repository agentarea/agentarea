-- A settled idempotency key is unique within its workspace, where every
-- lookup of it runs; across workspaces it was one global index.

-- +goose Up
DROP INDEX public.uq_payment_records_settled_idempotency_key;
CREATE UNIQUE INDEX uq_payment_records_settled_idempotency_key ON public.payment_records USING btree (workspace_id, idempotency_key) WHERE ((status)::text = 'completed'::text);

-- +goose Down
DROP INDEX public.uq_payment_records_settled_idempotency_key;
CREATE UNIQUE INDEX uq_payment_records_settled_idempotency_key ON public.payment_records USING btree (idempotency_key) WHERE ((status)::text = 'completed'::text);
