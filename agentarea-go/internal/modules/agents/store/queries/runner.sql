-- name: RecordRunnerHello :execrows
UPDATE clients SET
    models = CASE WHEN sqlc.arg(set_models)::bool THEN sqlc.narg(models)::jsonb ELSE models END,
    default_model = COALESCE(default_model, sqlc.narg(default_model)::text),
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;
