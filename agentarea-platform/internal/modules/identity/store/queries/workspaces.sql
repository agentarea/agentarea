-- name: WorkspaceSlugTaken :one
SELECT EXISTS (SELECT 1 FROM workspaces WHERE slug = @slug)::bool;

-- name: InsertWorkspace :one
INSERT INTO workspaces (id, slug, name, owner_user_id)
VALUES (@id, @slug, @name, @owner_user_id)
RETURNING id, slug, name, owner_user_id, logo_key;

-- name: OwnedWorkspaceIDs :many
SELECT id FROM workspaces WHERE owner_user_id = @owner_user_id ORDER BY created_at;

-- name: GetWorkspace :one
SELECT id, slug, name, owner_user_id, logo_key FROM workspaces WHERE id = @id;

-- name: ListWorkspacesForUser :many
SELECT id, slug, name, owner_user_id, logo_key FROM workspaces
WHERE owner_user_id = @user_id OR id = ANY(@member_ids::text[])
ORDER BY created_at;

-- name: SetWorkspaceLogo :exec
UPDATE workspaces SET logo_key = @logo_key, updated_at = @now WHERE id = @id;
