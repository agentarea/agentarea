-- name: StreamInsertLock :exec
SELECT pg_advisory_xact_lock(1397051697, hashtext(@stream_id::text));

-- name: EventSeen :one
SELECT EXISTS (SELECT 1 FROM stream_events WHERE workspace_id = @workspace_id AND event_id = @event_id);

-- name: InsertEvent :one
INSERT INTO stream_events (received_at, stream_id, event_id, event_key, kind, source, subject, occurred_at,
    correlation_id, causation_id, source_id, source_type, session_key, sender, depth, data, attachments,
    workspace_id, created_by, routed_at, subscribers)
VALUES (@received_at, @stream_id, @event_id, @event_key, @kind, @source, sqlc.narg(subject), @occurred_at,
    sqlc.narg(correlation_id), sqlc.narg(causation_id), sqlc.narg(source_id), sqlc.narg(source_type),
    sqlc.narg(session_key), sqlc.narg(sender), @depth, @data, @attachments, @workspace_id, @created_by,
    sqlc.narg(routed_at), sqlc.narg(subscribers))
ON CONFLICT (event_id, received_at) DO NOTHING
RETURNING sequence;

-- name: CountEvent :exec
INSERT INTO stream_event_counts (workspace_id, created_by, stream_id, day, source_type, count)
VALUES (@workspace_id, @created_by, @stream_id, @day, @source_type, 1)
ON CONFLICT (workspace_id, stream_id, day, source_type) DO UPDATE SET count = stream_event_counts.count + 1;

-- name: MarkRouted :exec
UPDATE stream_events SET routed_at = COALESCE(routed_at, @routed_at), subscribers = @subscribers
WHERE workspace_id = @workspace_id AND event_id = @event_id AND received_at = @received_at;

-- name: MarkReactions :exec
UPDATE stream_events SET reacted = @reacted, skipped = @skipped, errors = @errors
WHERE workspace_id = @workspace_id AND event_id = @event_id AND received_at = @received_at;

-- name: EventByID :one
SELECT * FROM stream_events WHERE workspace_id = @workspace_id AND event_id = @event_id LIMIT 1;

-- name: EventsAfter :many
SELECT * FROM stream_events
WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND sequence > @after
ORDER BY sequence LIMIT @lim;

-- name: EventsBefore :many
SELECT * FROM stream_events
WHERE workspace_id = @workspace_id AND stream_id = @stream_id
  AND (sqlc.narg(before)::bigint IS NULL OR sequence < sqlc.narg(before)::bigint)
ORDER BY sequence DESC LIMIT @lim;

-- name: EventsSince :many
SELECT * FROM stream_events
WHERE workspace_id = @workspace_id AND stream_id = @stream_id AND received_at >= @since AND sequence > @after
ORDER BY sequence LIMIT @lim;

-- name: HeadSequence :one
SELECT COALESCE(max(sequence), 0)::bigint FROM stream_events WHERE workspace_id = @workspace_id AND stream_id = @stream_id;

-- name: LastReceivedByStream :many
SELECT stream_id, max(received_at)::timestamptz AS last_received_at FROM stream_events
WHERE workspace_id = @workspace_id AND stream_id = ANY(@stream_ids::uuid[])
GROUP BY stream_id;

-- FeedEvents is the workspace feed, newest first; facet-less filters are all optional.
-- name: FeedEvents :many
SELECT * FROM stream_events e
WHERE e.workspace_id = @workspace_id AND e.stream_id = ANY(@stream_ids::uuid[])
  AND (sqlc.narg(stream_id)::uuid IS NULL OR e.stream_id = sqlc.narg(stream_id)::uuid)
  AND (sqlc.narg(source_type)::varchar IS NULL OR e.source_type = sqlc.narg(source_type)::varchar)
  AND (@platform::bool OR e.source_type IS DISTINCT FROM 'platform')
  AND (sqlc.narg(exact_kind)::varchar IS NULL OR e.kind = sqlc.narg(exact_kind)::varchar)
  AND (sqlc.narg(kind_prefix)::text IS NULL OR starts_with(e.kind, sqlc.narg(kind_prefix)::text))
  AND (sqlc.narg(sender)::varchar IS NULL OR e.sender = sqlc.narg(sender)::varchar)
  AND (sqlc.narg(session_key)::varchar IS NULL OR e.session_key = sqlc.narg(session_key)::varchar)
  AND (sqlc.narg(result)::text IS NULL OR (
        CASE
          WHEN e.routed_at IS NULL THEN 'queued'
          WHEN GREATEST(COALESCE(e.subscribers, 0), e.reacted) = 0 THEN 'no_handlers'
          WHEN e.errors > 0 THEN 'error'
          WHEN e.reacted < GREATEST(COALESCE(e.subscribers, 0), e.reacted) THEN 'processing'
          WHEN e.skipped = e.reacted THEN 'skipped'
          ELSE 'handled'
        END) = sqlc.narg(result)::text)
  AND (sqlc.narg(since)::timestamptz IS NULL OR e.received_at >= sqlc.narg(since)::timestamptz)
  AND (sqlc.narg(until)::timestamptz IS NULL OR e.received_at < sqlc.narg(until)::timestamptz)
  AND (sqlc.narg(event_id)::uuid IS NULL OR e.event_id = sqlc.narg(event_id)::uuid)
  AND (sqlc.narg(before)::bigint IS NULL OR e.sequence < sqlc.narg(before)::bigint)
ORDER BY e.sequence DESC
LIMIT @lim;

-- name: FacetsByStream :many
SELECT stream_id, sum(count)::bigint AS n FROM stream_event_counts
WHERE workspace_id = @workspace_id AND stream_id = ANY(@stream_ids::uuid[])
  AND (sqlc.narg(source_type)::varchar IS NULL OR source_type = sqlc.narg(source_type)::varchar)
GROUP BY stream_id;

-- name: FacetsBySourceType :many
SELECT source_type, sum(count)::bigint AS n FROM stream_event_counts
WHERE workspace_id = @workspace_id AND stream_id = ANY(@stream_ids::uuid[]) AND source_type <> ''
  AND (sqlc.narg(stream_id)::uuid IS NULL OR stream_id = sqlc.narg(stream_id)::uuid)
GROUP BY source_type;

-- CappedFacets counts the first cap+1 matching events by stream and source type.
-- name: CappedFacets :many
SELECT m.stream_id, m.source_type, count(*)::bigint AS n FROM (
  SELECT e.stream_id, e.source_type FROM stream_events e
  WHERE e.workspace_id = @workspace_id AND e.stream_id = ANY(@stream_ids::uuid[])
    AND (NOT @either::bool OR e.stream_id = sqlc.narg(stream_id)::uuid OR e.source_type = sqlc.narg(source_type)::varchar)
    AND (sqlc.narg(exact_kind)::varchar IS NULL OR e.kind = sqlc.narg(exact_kind)::varchar)
    AND (sqlc.narg(kind_prefix)::text IS NULL OR starts_with(e.kind, sqlc.narg(kind_prefix)::text))
    AND (sqlc.narg(sender)::varchar IS NULL OR e.sender = sqlc.narg(sender)::varchar)
    AND (sqlc.narg(session_key)::varchar IS NULL OR e.session_key = sqlc.narg(session_key)::varchar)
    AND (sqlc.narg(result)::text IS NULL OR (
          CASE
            WHEN e.routed_at IS NULL THEN 'queued'
            WHEN GREATEST(COALESCE(e.subscribers, 0), e.reacted) = 0 THEN 'no_handlers'
            WHEN e.errors > 0 THEN 'error'
            WHEN e.reacted < GREATEST(COALESCE(e.subscribers, 0), e.reacted) THEN 'processing'
            WHEN e.skipped = e.reacted THEN 'skipped'
            ELSE 'handled'
          END) = sqlc.narg(result)::text)
    AND (sqlc.narg(since)::timestamptz IS NULL OR e.received_at >= sqlc.narg(since)::timestamptz)
    AND (sqlc.narg(until)::timestamptz IS NULL OR e.received_at < sqlc.narg(until)::timestamptz)
    AND (sqlc.narg(event_id)::uuid IS NULL OR e.event_id = sqlc.narg(event_id)::uuid)
  LIMIT @lim
) m GROUP BY m.stream_id, m.source_type;
