-- name: InsertVideoJob :exec
INSERT INTO video_generation_jobs (id, created_at, updated_at, workspace_id, created_by, model_instance_id, task_id,
    provider_job_id, prompt, status, funding)
VALUES (@id, @now, @now, @workspace_id, @created_by, @model_instance_id, @task_id::text, @provider_job_id, @prompt, @status, @funding);

-- name: GetVideoJobOfTask :one
SELECT id, model_instance_id, provider_job_id, status, billed_call_ref, file_path, error, funding, billing
FROM video_generation_jobs
WHERE id = @id AND workspace_id = @workspace_id AND task_id = @task_id::text;

-- name: SetVideoJobStatus :exec
UPDATE video_generation_jobs SET status = @status, error = @error, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: RecordVideoSaved :execrows
UPDATE video_generation_jobs
SET status = 'completed', file_path = @file_path, cost_usd = sqlc.narg(cost_usd)::numeric,
    billed_cost = sqlc.narg(billed_cost)::numeric, billing = @billing, billed_call_ref = @call_ref, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id AND file_path IS NULL;

-- name: VideoJobBilledCallRef :one
SELECT billed_call_ref FROM video_generation_jobs WHERE id = @id AND workspace_id = @workspace_id;
