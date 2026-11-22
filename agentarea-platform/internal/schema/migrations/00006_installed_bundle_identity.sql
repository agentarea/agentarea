-- A deploy finds the install it updates by id (ADR-0060): who deployed it
-- last, and where the folder came from (the CLI's git remote, commit and
-- path; shown, never checked).

-- +goose Up
ALTER TABLE public.installed_bundles ADD COLUMN updated_by character varying(255);
ALTER TABLE public.installed_bundles ADD COLUMN source jsonb;

-- +goose Down
ALTER TABLE public.installed_bundles DROP COLUMN source;
ALTER TABLE public.installed_bundles DROP COLUMN updated_by;
