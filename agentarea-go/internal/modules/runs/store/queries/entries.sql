-- name: InsertEntry :exec
INSERT INTO task_conversation_entries (
    id, task_id, seq, event_id, kind, role, content, tool_calls, tool_call_id, name,
    attachments, execution_id, iteration, meta, correlation_id, causation_id, body_ref,
    workspace_id, created_by, created_at
) VALUES (
    @id, @task_id, @seq, @event_id, @kind, @role, @content, sqlc.narg(tool_calls)::text::jsonb,
    sqlc.narg(tool_call_id), sqlc.narg(name), sqlc.narg(attachments)::text::jsonb, sqlc.narg(execution_id),
    sqlc.narg(iteration), sqlc.narg(meta)::text::jsonb, sqlc.narg(correlation_id), sqlc.narg(causation_id),
    sqlc.narg(body_ref), @workspace_id, @created_by, COALESCE(sqlc.narg(created_at)::timestamptz, now())
) ON CONFLICT ON CONSTRAINT uq_task_conversation_entries_event DO NOTHING;

-- name: WindowEntries :many
SELECT seq, event_id, kind, role, content, COALESCE(tool_calls::text, '')::text AS tool_calls, tool_call_id, name,
    COALESCE(attachments::text, '')::text AS attachments, COALESCE(meta::text, '')::text AS meta, iteration, execution_id, created_at, body_ref
FROM task_conversation_entries e
WHERE e.task_id = @task_id AND e.workspace_id = @workspace_id AND e.seq < @end_seq
  AND e.kind IN ('message', 'compaction')
  AND (e.seq >= COALESCE((SELECT max(c.seq) FROM task_conversation_entries c
          WHERE c.task_id = @task_id AND c.workspace_id = @workspace_id AND c.seq < @end_seq
            AND c.kind = 'compaction'), 0)
       OR e.seq = (SELECT min(s.seq) FROM task_conversation_entries s
          WHERE s.task_id = @task_id AND s.workspace_id = @workspace_id AND s.seq < @end_seq
            AND s.kind = 'message' AND s.role = 'system'))
ORDER BY e.seq;

-- name: LatestFeedEntries :many
SELECT seq, event_id, kind, role, content, COALESCE(tool_calls::text, '')::text AS tool_calls, tool_call_id, name,
    COALESCE(attachments::text, '')::text AS attachments, COALESCE(meta::text, '')::text AS meta, iteration, execution_id, created_at, body_ref
FROM task_conversation_entries
WHERE task_id = @task_id AND workspace_id = @workspace_id
  AND (kind = 'event' OR (kind = 'message' AND role = 'user'))
  AND (cardinality(sqlc.arg(event_types)::text[]) = 0
       OR (kind = 'event' AND name = ANY(sqlc.arg(event_types)::text[]))
       OR ('message.received' = ANY(sqlc.arg(event_types)::text[]) AND kind = 'message' AND role = 'user'))
ORDER BY seq DESC
LIMIT @max_rows;
