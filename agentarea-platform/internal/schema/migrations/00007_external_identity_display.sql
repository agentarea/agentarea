-- How the messenger named a linked account when it was linked: the
-- @username and the person's name, shown next to the numeric id. Rows linked
-- before this have neither.

-- +goose Up
ALTER TABLE public.user_external_identities ADD COLUMN username character varying(255);
ALTER TABLE public.user_external_identities ADD COLUMN display_name character varying(255);

-- +goose Down
ALTER TABLE public.user_external_identities DROP COLUMN display_name;
ALTER TABLE public.user_external_identities DROP COLUMN username;
