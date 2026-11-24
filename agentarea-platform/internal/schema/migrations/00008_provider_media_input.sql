-- What a provider takes in one request: the bytes and the longer edge of one
-- image (NULL is unstated; such images are sent as they are), and whether it
-- reads a PDF sent as a file.

-- +goose Up
ALTER TABLE public.provider_specs ADD COLUMN max_image_bytes integer;
ALTER TABLE public.provider_specs ADD COLUMN max_image_edge integer;
ALTER TABLE public.provider_specs ADD COLUMN pdf_input boolean DEFAULT false NOT NULL;

-- +goose Down
ALTER TABLE public.provider_specs DROP COLUMN pdf_input;
ALTER TABLE public.provider_specs DROP COLUMN max_image_edge;
ALTER TABLE public.provider_specs DROP COLUMN max_image_bytes;
