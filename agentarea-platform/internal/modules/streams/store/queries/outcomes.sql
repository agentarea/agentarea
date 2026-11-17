-- name: LockTrigger :one
SELECT id FROM triggers WHERE id = @id AND workspace_id = @workspace_id FOR UPDATE;

-- name: ResetTriggerFailures :exec
UPDATE triggers SET consecutive_failures = 0, updated_at = @at
WHERE id = @id AND workspace_id = @workspace_id AND consecutive_failures > 0;

-- name: LatestFiringOfTask :one
SELECT id, status FROM trigger_executions
WHERE trigger_id = @trigger_id AND task_id = @task_id AND workspace_id = @workspace_id
ORDER BY executed_at DESC
LIMIT 1
FOR UPDATE;

-- name: MarkFiringFailed :exec
UPDATE trigger_executions SET status = 'failed', error_message = sqlc.narg(error_message), updated_at = @at
WHERE id = @id AND workspace_id = @workspace_id;
