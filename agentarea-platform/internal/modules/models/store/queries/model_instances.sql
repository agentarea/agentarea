-- name: GetInstance :one
SELECT id, provider_config_id, model_spec_id, name, description, is_active, is_public,
       workspace_id, created_by, created_at, updated_at, tags
FROM model_instances mi
WHERE mi.id = @id AND (mi.workspace_id = @workspace_id
    OR (mi.workspace_id = 'platform'
        AND mi.provider_config_id IN (SELECT pc.id FROM provider_configs pc WHERE pc.managed_by = 'platform')));

-- name: ListInstanceIDs :many
SELECT mi.id FROM model_instances mi
WHERE (mi.workspace_id = @workspace_id
    OR (mi.workspace_id = 'platform'
        AND mi.provider_config_id IN (SELECT pc.id FROM provider_configs pc WHERE pc.managed_by = 'platform')))
  AND (NOT @by_config::bool OR mi.provider_config_id = @provider_config_id)
  AND (NOT @by_spec::bool OR mi.model_spec_id = @model_spec_id)
  AND (NOT @by_active::bool OR mi.is_active = @is_active)
  AND (NOT @by_ids::bool OR mi.id = ANY(@ids::uuid[]))
ORDER BY mi.created_at DESC
LIMIT 100;

-- name: InstancesByIDs :many
SELECT id, provider_config_id, model_spec_id, name, description, is_active, is_public,
       workspace_id, created_by, created_at, updated_at, tags
FROM model_instances mi
WHERE mi.id = ANY(@ids::uuid[]) AND (mi.workspace_id = @workspace_id
    OR (mi.workspace_id = 'platform'
        AND mi.provider_config_id IN (SELECT pc.id FROM provider_configs pc WHERE pc.managed_by = 'platform')))
ORDER BY mi.created_at DESC;

-- name: VisibleInstanceSpecs :many
SELECT mi.id, mi.model_spec_id FROM model_instances mi
WHERE mi.workspace_id = @workspace_id
    OR (mi.workspace_id = 'platform'
        AND mi.provider_config_id IN (SELECT pc.id FROM provider_configs pc WHERE pc.managed_by = 'platform'));

-- name: ConfigsOfInstances :many
SELECT id, provider_spec_id, name, description, api_key, endpoint_url, is_active, is_public,
       workspace_id, created_by, created_at, updated_at, api_key_secret_id, managed_by
FROM provider_configs WHERE id = ANY(@ids::uuid[]);

-- name: InsertInstance :exec
INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, description, is_active, is_public,
    workspace_id, created_by, created_at, updated_at, tags)
VALUES (@id, @provider_config_id, @model_spec_id, @name, @description, @is_active, @is_public,
    @workspace_id, @created_by, @now, @now, '[]'::jsonb);

-- name: DeleteInstance :execrows
DELETE FROM model_instances WHERE id = @id AND workspace_id = @workspace_id;

-- name: UsedModelSpecs :many
SELECT DISTINCT model_spec_id FROM model_instances WHERE model_spec_id = ANY(@ids::uuid[]);
