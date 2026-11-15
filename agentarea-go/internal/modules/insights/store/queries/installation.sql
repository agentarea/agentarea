-- name: InsertInstallation :exec
INSERT INTO installation (id, created_at, updated_at)
VALUES (@id, @now, @now)
ON CONFLICT DO NOTHING;

-- name: GetInstallation :one
SELECT id FROM installation LIMIT 1;
