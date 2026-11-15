-- Catalog agents and skills as agents installs them (catalog_agent_repository.py,
-- catalog_skill_repository.py): the platform's registries and the caller's own.

-- name: CatalogAgentPresets :many
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.registry_id, ri.registry_trust, ri.registry_workspace_id
FROM registry_items ri
WHERE ri.registry_type = 'agents' AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND ri.tags @> '["preset"]'::jsonb
ORDER BY ri.recommendation_rank NULLS LAST, ri.name;

-- name: CatalogItemOfType :one
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.registry_id, ri.registry_trust, ri.registry_workspace_id
FROM registry_items ri
WHERE ri.registry_type = @registry_type AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND ri.id = @id;

-- name: CatalogSkillByKey :one
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.registry_id, ri.registry_trust, ri.registry_workspace_id
FROM registry_items ri
WHERE ri.registry_type = 'skills' AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND (ri.name = @key::text OR ri.name LIKE @prefix::text)
ORDER BY ri.updated_at DESC, ri.id
LIMIT 1;

-- name: MarkItemInstalled :exec
INSERT INTO registry_item_installs (id, registry_item_id, workspace_id, installed_entity_id, installed_version, created_at, updated_at)
VALUES (@id, @registry_item_id, @workspace_id, @installed_entity_id, sqlc.narg(installed_version), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (registry_item_id, workspace_id) DO UPDATE SET
    installed_entity_id = EXCLUDED.installed_entity_id,
    installed_version = EXCLUDED.installed_version,
    updated_at = CURRENT_TIMESTAMP;

-- name: SkillProvenance :many
SELECT ri.id, ri.registry_id, ri.registry_trust
FROM registry_items ri
WHERE ri.registry_type = 'skills'
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
  AND ri.id = ANY(@ids::uuid[]);

-- name: CatalogAgentItems :many
SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.registry_id, ri.registry_trust, ri.registry_workspace_id
FROM registry_items ri
WHERE ri.registry_type = 'agents' AND ri.registry_active
  AND (ri.registry_workspace_id IS NULL OR ri.registry_workspace_id = @workspace_id::text)
ORDER BY ri.name;
