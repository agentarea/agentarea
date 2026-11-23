-- name: ListExternalIdentities :many
SELECT id, provider, external_id, created_at FROM user_external_identities
WHERE user_id = @user_id AND revoked_at IS NULL ORDER BY created_at;

-- name: RevokeExternalIdentity :execrows
UPDATE user_external_identities SET revoked_at = @now, updated_at = @now
WHERE id = @id AND user_id = @user_id AND revoked_at IS NULL;

-- name: ExternalIdentityHolder :one
SELECT user_id FROM user_external_identities
WHERE provider = @provider AND external_id = @external_id AND revoked_at IS NULL;

-- name: InsertExternalIdentity :one
INSERT INTO user_external_identities (id, created_at, updated_at, user_id, provider, external_id, method)
VALUES (@id, @now, @now, @user_id, @provider, @external_id, @method)
RETURNING id, provider, external_id, created_at;

-- LinkedExternalIDs reads only the columns user_external_identities has had from the baseline.
-- name: LinkedExternalIDs :many
SELECT external_id FROM user_external_identities
WHERE user_id = @user_id AND provider = @provider AND revoked_at IS NULL
ORDER BY created_at DESC, id;
