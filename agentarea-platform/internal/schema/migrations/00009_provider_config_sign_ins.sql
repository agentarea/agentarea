-- A ChatGPT sign-in a member started on a provider configuration and has not
-- finished: the device code the issuer handed out, kept here so only that
-- member can finish it, on that configuration, before it expires.

-- +goose Up
CREATE TABLE public.provider_config_sign_ins (
    provider_config_id uuid NOT NULL REFERENCES public.provider_configs(id) ON DELETE CASCADE,
    user_id character varying(255) NOT NULL,
    workspace_id character varying(255) NOT NULL,
    device_auth_id character varying NOT NULL,
    user_code character varying NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    PRIMARY KEY (provider_config_id, user_id)
);

-- +goose Down
DROP TABLE public.provider_config_sign_ins;
