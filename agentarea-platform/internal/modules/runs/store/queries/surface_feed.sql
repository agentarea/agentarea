-- name: SurfaceFeedAfter :many
SELECT seq, event_id, kind, role, content, COALESCE(tool_calls::text, '')::text AS tool_calls, tool_call_id, name,
    COALESCE(attachments::text, '')::text AS attachments, COALESCE(meta::text, '')::text AS meta, iteration,
    execution_id, created_at, body_ref
FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id
  AND (kind = 'event' OR (kind = 'message' AND role = 'user'))
  AND seq > @after_seq
ORDER BY seq
LIMIT @max_rows;

-- name: SurfaceFeedPage :many
SELECT seq, event_id, kind, role, content, COALESCE(tool_calls::text, '')::text AS tool_calls, tool_call_id, name,
    COALESCE(attachments::text, '')::text AS attachments, COALESCE(meta::text, '')::text AS meta, iteration,
    execution_id, created_at, body_ref
FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id
  AND (kind = 'event' OR (kind = 'message' AND role = 'user'))
  AND (sqlc.narg(event_type)::text IS NULL
       OR (sqlc.narg(event_type)::text = 'message.received' AND kind = 'message' AND role = 'user')
       OR (sqlc.narg(event_type)::text <> 'message.received' AND kind = 'event' AND name = sqlc.narg(event_type)::text))
ORDER BY seq
LIMIT @max_rows OFFSET @skip;

-- name: SurfaceFeedCount :one
SELECT count(*) FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id
  AND (kind = 'event' OR (kind = 'message' AND role = 'user'))
  AND (sqlc.narg(event_type)::text IS NULL
       OR (sqlc.narg(event_type)::text = 'message.received' AND kind = 'message' AND role = 'user')
       OR (sqlc.narg(event_type)::text <> 'message.received' AND kind = 'event' AND name = sqlc.narg(event_type)::text));

-- name: SurfaceFeedAt :one
SELECT seq, event_id, kind, role, content, COALESCE(tool_calls::text, '')::text AS tool_calls, tool_call_id, name,
    COALESCE(attachments::text, '')::text AS attachments, COALESCE(meta::text, '')::text AS meta, iteration,
    execution_id, created_at, body_ref
FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id
  AND (kind = 'event' OR (kind = 'message' AND role = 'user'))
  AND seq = @seq;

-- name: SurfaceFeedBodies :many
SELECT seq, event_id, kind, role, content, COALESCE(tool_calls::text, '')::text AS tool_calls, tool_call_id, name,
    COALESCE(attachments::text, '')::text AS attachments, COALESCE(meta::text, '')::text AS meta, iteration,
    execution_id, created_at, body_ref
FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id AND kind = 'message'
  AND ((role = 'tool' AND tool_call_id = ANY(sqlc.arg(call_ids)::text[]))
       OR (role = 'assistant' AND EXISTS (
           SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(tool_calls) = 'array' THEN tool_calls ELSE '[]'::jsonb END) c
           WHERE c->>'id' = ANY(sqlc.arg(call_ids)::text[]))))
ORDER BY seq;
