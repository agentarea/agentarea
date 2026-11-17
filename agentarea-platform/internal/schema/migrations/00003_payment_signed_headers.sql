-- The signed payment a pending hold sent, so a retry of its call sends the
-- same payment again instead of signing a second one.

-- +goose Up
ALTER TABLE public.payment_records ADD COLUMN signed_headers json;

-- +goose Down
ALTER TABLE public.payment_records DROP COLUMN signed_headers;
