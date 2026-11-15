-- name: SurfaceApproval :one
SELECT id, created_by, client_id, client_name, mcp_instance_id, connector, tool, policy_name,
    arguments::text AS arguments, status, reason, approvers::text AS approvers, decided_by, decided_at,
    comment, expires_at, created_at
FROM tool_call_approvals
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SurfaceApprovalPage :many
SELECT id, created_by, client_id, client_name, mcp_instance_id, connector, tool, policy_name,
    arguments::text AS arguments, status, reason, approvers::text AS approvers, decided_by, decided_at,
    comment, expires_at, created_at
FROM tool_call_approvals
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(status)::text IS NULL
       OR (sqlc.narg(status)::text IN ('pending', 'approved') AND status = sqlc.narg(status)::text AND expires_at > @now)
       OR (sqlc.narg(status)::text = 'expired' AND (status = 'expired' OR (status IN ('pending', 'approved') AND expires_at <= @now)))
       OR (sqlc.narg(status)::text NOT IN ('pending', 'approved', 'expired') AND status = sqlc.narg(status)::text))
ORDER BY created_at DESC, id
LIMIT @max_rows OFFSET @skip;

-- name: SurfaceApprovalCount :one
SELECT count(*) FROM tool_call_approvals
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(status)::text IS NULL
       OR (sqlc.narg(status)::text IN ('pending', 'approved') AND status = sqlc.narg(status)::text AND expires_at > @now)
       OR (sqlc.narg(status)::text = 'expired' AND (status = 'expired' OR (status IN ('pending', 'approved') AND expires_at <= @now)))
       OR (sqlc.narg(status)::text NOT IN ('pending', 'approved', 'expired') AND status = sqlc.narg(status)::text));

-- name: SurfaceDecideApproval :one
UPDATE tool_call_approvals SET
    status = @new_status, decided_by = @decided_by, decided_at = @now, comment = sqlc.narg(comment),
    expires_at = COALESCE(sqlc.narg(expires_at)::timestamptz, expires_at),
    updated_at = sqlc.arg(updated_at)::timestamp
WHERE id = @id AND workspace_id = @workspace_id AND status = 'pending' AND expires_at > @now
RETURNING id, created_by, client_id, client_name, mcp_instance_id, connector, tool, policy_name,
    arguments::text AS arguments, status, reason, approvers::text AS approvers, decided_by, decided_at,
    comment, expires_at, created_at;
