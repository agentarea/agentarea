-- name: InsertInstallation :exec
INSERT INTO installation (id, created_at, updated_at)
VALUES (@id, @now, @now)
ON CONFLICT DO NOTHING;

-- name: GetInstallation :one
SELECT id FROM installation LIMIT 1;

-- name: LockInstallationForPulse :one
SELECT id, created_at, last_pulse_at FROM installation LIMIT 1 FOR UPDATE;

-- name: SetLastPulse :exec
UPDATE installation SET last_pulse_at = @at, updated_at = @at WHERE id = @id;
