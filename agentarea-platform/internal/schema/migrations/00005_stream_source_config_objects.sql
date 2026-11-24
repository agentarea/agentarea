-- A source's webhook_config is an object. An early run of the sources
-- migration left some as an array such as [null, {...}]; their objects are
-- merged back into one, and any other non-object becomes {}.

-- +goose Up
UPDATE public.stream_sources s
SET webhook_config = COALESCE((
        SELECT jsonb_object_agg(kv.key, kv.value)
        FROM jsonb_array_elements(s.webhook_config::jsonb) AS e(elem),
             jsonb_each(CASE WHEN jsonb_typeof(e.elem) = 'object' THEN e.elem ELSE '{}'::jsonb END) AS kv
    ), '{}'::jsonb)::json
WHERE json_typeof(s.webhook_config) = 'array';

UPDATE public.stream_sources
SET webhook_config = '{}'::json
WHERE webhook_config IS NOT NULL
  AND json_typeof(webhook_config) NOT IN ('object', 'array');

-- +goose Down
SELECT 1;
