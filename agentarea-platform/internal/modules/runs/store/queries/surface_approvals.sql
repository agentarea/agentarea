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

-- name: GateExpireLapsed :exec
UPDATE tool_call_approvals SET status = 'expired'
WHERE workspace_id = @workspace_id AND created_by = @created_by
  AND mcp_instance_id IS NOT DISTINCT FROM sqlc.narg(mcp_instance_id)::uuid
  AND tool = @tool AND arguments_hash = @arguments_hash
  AND status IN ('pending', 'approved') AND expires_at <= @now;

-- name: GateConsumeApproved :one
UPDATE tool_call_approvals SET status = 'consumed'
WHERE id = (
    SELECT a.id FROM tool_call_approvals a
    WHERE a.workspace_id = @workspace_id AND a.created_by = @created_by
      AND a.mcp_instance_id IS NOT DISTINCT FROM sqlc.narg(mcp_instance_id)::uuid
      AND a.tool = @tool AND a.arguments_hash = @arguments_hash
      AND a.status = 'approved' AND a.expires_at > @now
    ORDER BY a.decided_at LIMIT 1)
  AND workspace_id = @workspace_id AND status = 'approved' AND expires_at > @now
RETURNING id, decided_by, comment;

-- name: GateFindLive :one
SELECT id, decided_by, comment, connector, tool FROM tool_call_approvals
WHERE workspace_id = @workspace_id AND created_by = @created_by
  AND mcp_instance_id IS NOT DISTINCT FROM sqlc.narg(mcp_instance_id)::uuid
  AND tool = @tool AND arguments_hash = @arguments_hash
  AND status = @status AND expires_at > @now
ORDER BY created_at DESC LIMIT 1;

-- name: GateCreatePending :one
INSERT INTO tool_call_approvals (id, workspace_id, created_by, client_id, client_name, mcp_instance_id, connector, tool,
    policy_name, arguments, arguments_hash, status, reason, approvers, expires_at, created_at, updated_at)
VALUES (@id, @workspace_id, @created_by, sqlc.narg(client_id), sqlc.narg(client_name), sqlc.narg(mcp_instance_id)::uuid,
    @connector, @tool, @policy_name, @arguments::jsonb, @arguments_hash, 'pending', @reason, @approvers::jsonb,
    @expires_at, sqlc.arg(created_at)::timestamp, sqlc.arg(created_at)::timestamp)
ON CONFLICT DO NOTHING
RETURNING id;
