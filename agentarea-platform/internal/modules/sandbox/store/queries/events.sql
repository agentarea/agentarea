-- name: InsertArtifactEvent :exec
INSERT INTO artifact_events (id, created_at, updated_at, workspace_id, created_by, path, action, actor_type, agent_id, task_id)
VALUES (@id, @now, @now, @workspace_id, @created_by, @path, @action, @actor_type, @agent_id, @task_id);

-- name: ArtifactHistory :many
SELECT action, actor_type, created_by, agent_id, task_id, created_at
FROM artifact_events
WHERE workspace_id = @workspace_id AND path = @path
ORDER BY created_at DESC;

-- name: RenameArtifactEvents :exec
UPDATE artifact_events SET path = @destination, updated_at = @now
WHERE workspace_id = @workspace_id AND path = @source;
