-- name: MembershipExists :one
SELECT EXISTS (SELECT 1 FROM workspace_memberships WHERE workspace_id = @workspace_id AND user_id = @user_id)::bool;

-- name: InsertMembership :exec
INSERT INTO workspace_memberships (id, created_at, updated_at, workspace_id, user_id, invitation_id)
VALUES (@id, @now, @now, @workspace_id, @user_id, @invitation_id);

-- name: ListMemberships :many
SELECT user_id, created_at, invitation_id FROM workspace_memberships
WHERE workspace_id = @workspace_id ORDER BY created_at;

-- name: MembershipUserIDs :many
SELECT user_id FROM workspace_memberships WHERE workspace_id = @workspace_id;

-- name: DeleteMembership :exec
DELETE FROM workspace_memberships WHERE workspace_id = @workspace_id AND user_id = @user_id;
