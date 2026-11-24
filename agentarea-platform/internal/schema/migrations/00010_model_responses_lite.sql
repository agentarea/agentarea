-- A model on the ChatGPT backend that takes its tools the Responses Lite way
-- (codex-rs use_responses_lite): one additional_tools developer item instead of
-- the request's tools.

-- +goose Up
ALTER TABLE public.model_specs ADD COLUMN responses_lite boolean DEFAULT false NOT NULL;

-- +goose Down
ALTER TABLE public.model_specs DROP COLUMN responses_lite;
