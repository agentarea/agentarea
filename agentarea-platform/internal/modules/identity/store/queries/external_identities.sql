-- name: ListExternalIdentities :many
SELECT id, provider, external_id, username, display_name, created_at FROM user_external_identities
WHERE user_id = @user_id AND revoked_at IS NULL ORDER BY created_at;

-- name: RevokeExternalIdentity :execrows
UPDATE user_external_identities SET revoked_at = @now, updated_at = @now
WHERE id = @id AND user_id = @user_id AND revoked_at IS NULL;

-- name: ExternalIdentityHolder :one
SELECT user_id FROM user_external_identities
WHERE provider = @provider AND external_id = @external_id AND revoked_at IS NULL;

-- name: InsertExternalIdentity :one
INSERT INTO user_external_identities (id, created_at, updated_at, user_id, provider, external_id, method, username, display_name)
VALUES (@id, @now, @now, @user_id, @provider, @external_id, @method, sqlc.narg(username), sqlc.narg(display_name))
RETURNING id, provider, external_id, username, display_name, created_at;

-- name: RenameExternalIdentity :one
UPDATE user_external_identities
SET username = COALESCE(sqlc.narg(username), username),
    display_name = COALESCE(sqlc.narg(display_name), display_name),
    updated_at = @now
WHERE user_id = @user_id AND provider = @provider AND external_id = @external_id AND revoked_at IS NULL
RETURNING id, provider, external_id, username, display_name, created_at;
