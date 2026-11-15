-- ListRules orders as PolicyRuleRepository.list_rules: subject, then priority.
-- name: ListRules :many
SELECT id, subject_type, subject_id, target, effect, params, condition, enabled, priority, managed_by
FROM policies
WHERE workspace_id = @workspace_id
  AND (sqlc.narg(subject_type)::varchar IS NULL OR subject_type = sqlc.narg(subject_type)::varchar)
  AND (sqlc.narg(subject_id)::varchar IS NULL OR subject_id = sqlc.narg(subject_id)::varchar)
  AND (sqlc.narg(effect)::varchar IS NULL OR effect = sqlc.narg(effect)::varchar)
  AND (sqlc.narg(target)::varchar IS NULL OR target = sqlc.narg(target)::varchar)
  AND (sqlc.narg(enabled)::bool IS NULL OR enabled = sqlc.narg(enabled)::bool)
ORDER BY subject_type, subject_id, priority;

-- name: GetRule :one
SELECT id, subject_type, subject_id, target, effect, params, condition, enabled, priority, managed_by
FROM policies WHERE workspace_id = @workspace_id AND id = @id;

-- name: CreateRule :one
INSERT INTO policies (id, subject_type, subject_id, target, effect, params, condition, enabled, priority,
                      workspace_id, created_by, created_at, updated_at, managed_by)
VALUES (@id, @subject_type, @subject_id, @target, @effect, @params, sqlc.narg(condition), @enabled, @priority,
        @workspace_id, @created_by, @now, @now, sqlc.narg(managed_by))
RETURNING id, subject_type, subject_id, target, effect, params, condition, enabled, priority, managed_by;

-- name: UpdateRule :one
UPDATE policies SET
    subject_type = COALESCE(sqlc.narg(subject_type)::varchar, subject_type),
    subject_id = COALESCE(sqlc.narg(subject_id)::varchar, subject_id),
    target = COALESCE(sqlc.narg(target)::varchar, target),
    effect = COALESCE(sqlc.narg(effect)::varchar, effect),
    params = COALESCE(sqlc.narg(params)::jsonb, params),
    condition = COALESCE(sqlc.narg(condition)::text, condition),
    enabled = COALESCE(sqlc.narg(enabled)::bool, enabled),
    priority = COALESCE(sqlc.narg(priority)::int, priority),
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id
RETURNING id, subject_type, subject_id, target, effect, params, condition, enabled, priority, managed_by;

-- name: DeleteRule :execrows
DELETE FROM policies WHERE workspace_id = @workspace_id AND id = @id;
