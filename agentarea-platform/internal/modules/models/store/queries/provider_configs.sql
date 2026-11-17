-- name: GetConfig :one
SELECT id, provider_spec_id, name, description, api_key, endpoint_url, is_active, is_public,
       workspace_id, created_by, created_at, updated_at, api_key_secret_id, managed_by
FROM provider_configs
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- ListConfigIDs is list_all: newest first, at most 100.
-- name: ListConfigIDs :many
SELECT id FROM provider_configs
WHERE (workspace_id = @workspace_id OR managed_by = 'platform')
  AND (NOT @by_spec::bool OR provider_spec_id = @provider_spec_id)
  AND (NOT @by_active::bool OR is_active = @is_active)
ORDER BY created_at DESC
LIMIT 100;

-- name: ConfigsByIDs :many
SELECT id, provider_spec_id, name, description, api_key, endpoint_url, is_active, is_public,
       workspace_id, created_by, created_at, updated_at, api_key_secret_id, managed_by
FROM provider_configs
WHERE id = ANY(@ids::uuid[]) AND (workspace_id = @workspace_id OR managed_by = 'platform')
ORDER BY created_at DESC;

-- name: OwnsConfig :one
SELECT count(*) FROM provider_configs WHERE id = @id AND workspace_id = @workspace_id;

-- name: InsertConfig :exec
INSERT INTO provider_configs (id, provider_spec_id, name, description, api_key, endpoint_url, is_active, is_public,
    workspace_id, created_by, created_at, updated_at, api_key_secret_id, managed_by)
VALUES (@id, @provider_spec_id, @name, @description, @api_key, @endpoint_url, @is_active, @is_public,
    @workspace_id, @created_by, @now, @now, @api_key_secret_id, NULL);

-- name: UpdateConfig :execrows
UPDATE provider_configs SET
    name = @name, description = @description, api_key = @api_key, endpoint_url = @endpoint_url,
    is_active = @is_active, is_public = @is_public, api_key_secret_id = @api_key_secret_id, updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: DeleteConfig :execrows
DELETE FROM provider_configs WHERE id = @id AND workspace_id = @workspace_id;

-- name: InstanceSpecsOfConfigs :many
SELECT provider_config_id, model_spec_id FROM model_instances
WHERE provider_config_id = ANY(@ids::uuid[]) AND workspace_id = @workspace_id
ORDER BY created_at;

-- name: ProviderSpecIDsWithVisibleConfigs :many
SELECT DISTINCT provider_spec_id FROM provider_configs
WHERE workspace_id = @workspace_id OR managed_by = 'platform';

-- name: UsedProviderSpecs :many
SELECT DISTINCT provider_spec_id FROM provider_configs WHERE provider_spec_id = ANY(@ids::uuid[]);
