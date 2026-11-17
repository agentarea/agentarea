-- name: InventoryAgents :many
SELECT id, name FROM agents
WHERE workspace_id = @workspace_id
  AND (@include_archived::bool OR (status <> 'archived' AND harness_client_id IS NULL))
ORDER BY created_at DESC;

-- name: InventorySkills :many
SELECT id, name FROM skills WHERE workspace_id = @workspace_id ORDER BY workspace_id, id;

-- name: CollectionExists :one
SELECT EXISTS (SELECT 1 FROM skill_collections WHERE workspace_id = @workspace_id AND id = @id)::bool;

-- name: MoveSkillForks :execrows
UPDATE skills s SET registry_item_id = @new_id::uuid
WHERE s.registry_item_id = @old_id::uuid
  AND NOT EXISTS (SELECT 1 FROM skills other WHERE other.workspace_id = s.workspace_id AND other.registry_item_id = @new_id::uuid);

-- name: MoveAgentItems :execrows
UPDATE agents SET registry_item_id = @new_id::text WHERE registry_item_id = @old_id::text;

-- name: SkillReferencedItems :many
SELECT DISTINCT registry_item_id::uuid FROM skills WHERE registry_item_id = ANY(@ids::uuid[]);

-- name: AgentReferencedItems :many
SELECT DISTINCT registry_item_id::text FROM agents WHERE registry_item_id = ANY(@ids::text[]);

-- name: DeletePlatformSkills :many
DELETE FROM skills WHERE workspace_id = 'platform' AND id = ANY(@ids::uuid[]) RETURNING id;
