-- SourceByID runs before any workspace is known: a polled item names only its source.
-- name: SourceByID :one
SELECT * FROM stream_sources WHERE id = @id;
