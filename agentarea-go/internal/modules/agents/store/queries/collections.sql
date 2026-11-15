-- name: InsertCollection :exec
INSERT INTO skill_collections (id, created_at, updated_at, workspace_id, created_by, name, slug, description)
VALUES (@id, @now, @now, @workspace_id, @created_by, @name, @slug, @description);

-- name: GetCollection :one
SELECT id, name, slug, description FROM skill_collections WHERE workspace_id = @workspace_id AND id = @id;

-- name: CollectionSlugTaken :one
SELECT EXISTS (SELECT 1 FROM skill_collections WHERE workspace_id = @workspace_id AND slug = @slug)::bool;

-- name: ListCollections :many
SELECT id, name, slug, description FROM skill_collections WHERE workspace_id = @workspace_id ORDER BY created_at DESC;

-- name: CollectionSkillCounts :many
SELECT cs.collection_id, count(cs.skill_id)::bigint AS n
FROM collection_skills cs JOIN skill_collections c ON c.id = cs.collection_id
WHERE c.workspace_id = @workspace_id GROUP BY cs.collection_id;

-- name: CollectionSkillCount :one
SELECT count(skill_id)::bigint FROM collection_skills WHERE collection_id = @collection_id;

-- name: CollectionSkills :many
SELECT s.id, s.name FROM collection_skills cs JOIN skills s ON s.id = cs.skill_id
WHERE cs.collection_id = @collection_id AND s.workspace_id = @workspace_id;

-- name: UpdateCollection :exec
UPDATE skill_collections SET
    name = CASE WHEN @set_name::bool THEN @name::varchar ELSE name END,
    description = CASE WHEN @set_description::bool THEN sqlc.narg(description)::text ELSE description END,
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeleteCollection :execrows
DELETE FROM skill_collections WHERE workspace_id = @workspace_id AND id = @id;

-- name: CollectionHasSkill :one
SELECT EXISTS (SELECT 1 FROM collection_skills WHERE collection_id = @collection_id AND skill_id = @skill_id)::bool;

-- name: InsertCollectionSkill :exec
INSERT INTO collection_skills (collection_id, skill_id, created_at) VALUES (@collection_id, @skill_id, @now);

-- name: DeleteCollectionSkill :exec
DELETE FROM collection_skills WHERE collection_id = @collection_id AND skill_id = @skill_id;
