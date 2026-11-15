-- name: InsertInvitation :one
INSERT INTO workspace_invitations (id, created_at, updated_at, workspace_id, email, token_hash, invited_by, status, expires_at)
VALUES (@id, @now, @now, @workspace_id, @email, @token_hash, @invited_by, 'pending', @expires_at)
RETURNING id, created_at, workspace_id, email, invited_by, status, expires_at, accepted_at, accepted_by_user_id, membership_granted_at;

-- name: InvitationByTokenHash :one
SELECT id, created_at, workspace_id, email, invited_by, status, expires_at, accepted_at, accepted_by_user_id, membership_granted_at
FROM workspace_invitations WHERE token_hash = @token_hash;

-- name: MarkInvitationAccepted :exec
UPDATE workspace_invitations
SET status = 'accepted', accepted_at = @accepted_at, accepted_by_user_id = @user_id, updated_at = @now
WHERE id = @id;

-- name: LockInvitation :one
SELECT status, accepted_by_user_id, membership_granted_at
FROM workspace_invitations WHERE id = @id FOR UPDATE;

-- name: StampMembershipGranted :exec
UPDATE workspace_invitations SET membership_granted_at = @now, updated_at = @updated_at WHERE id = @id;

-- name: ListPendingInvitations :many
SELECT id, created_at, workspace_id, email, invited_by, status, expires_at, accepted_at, accepted_by_user_id, membership_granted_at
FROM workspace_invitations WHERE workspace_id = @workspace_id AND status = 'pending'
ORDER BY created_at DESC;

-- name: GetInvitation :one
SELECT id, created_at, workspace_id, email, invited_by, status, expires_at, accepted_at, accepted_by_user_id, membership_granted_at
FROM workspace_invitations WHERE id = @id;

-- name: RevokeInvitation :exec
UPDATE workspace_invitations SET status = 'revoked', updated_at = @now WHERE id = @id AND workspace_id = @workspace_id;

-- name: EmailsJoinedThrough :many
SELECT email::text FROM workspace_invitations
WHERE workspace_id = @workspace_id AND accepted_by_user_id = @user_id AND email IS NOT NULL;

-- name: PendingAddressedInvitations :many
SELECT id, email::text FROM workspace_invitations
WHERE workspace_id = @workspace_id AND status = 'pending' AND email IS NOT NULL;

-- name: RevokeInvitationsAcceptedBy :exec
UPDATE workspace_invitations SET status = 'revoked', updated_at = @now
WHERE workspace_id = @workspace_id AND accepted_by_user_id = @user_id;
