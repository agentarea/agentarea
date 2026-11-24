-- name: SkillGet :one
SELECT id, name, slug, description, source_type, source_url, network_scope, workspace_id, created_by,
       created_at, updated_at, registry_item_id, s3_path, content
FROM skills WHERE workspace_id = @workspace_id AND id = @id;

-- name: SkillGetForUpdate :one
SELECT id, name, slug, description, source_type, source_url, network_scope, workspace_id, created_by,
       created_at, updated_at, registry_item_id, s3_path, content
FROM skills WHERE workspace_id = @workspace_id AND id = @id FOR UPDATE;

-- name: SkillSlugTaken :one
SELECT EXISTS (SELECT 1 FROM skills WHERE workspace_id = @workspace_id AND slug = @slug)::bool;

-- name: SkillInsert :exec
INSERT INTO skills (id, name, slug, description, source_type, source_url, content, s3_path, network_scope,
                    workspace_id, created_by, created_at, updated_at)
VALUES (@id, @name, @slug, sqlc.narg(description)::text, @source_type, sqlc.narg(source_url)::varchar, NULL, NULL, 'private',
        @workspace_id, @created_by, @now, @now);

-- name: SkillUpdateMeta :exec
UPDATE skills SET
    name = COALESCE(sqlc.narg(name)::varchar, name),
    description = COALESCE(sqlc.narg(description)::text, description),
    source_url = COALESCE(sqlc.narg(source_url)::varchar, source_url),
    updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: SkillSetPackage :exec
UPDATE skills SET s3_path = @s3_path, content = NULL, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: SkillSwapPackage :one
UPDATE skills SET s3_path = @s3_path, content = NULL, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id AND s3_path IS NOT DISTINCT FROM sqlc.narg(expect)::varchar
RETURNING id;

-- name: SkillClearContent :exec
UPDATE skills SET content = NULL, updated_at = @now WHERE workspace_id = @workspace_id AND id = @id;

-- name: SkillDelete :execrows
DELETE FROM skills WHERE workspace_id = @workspace_id AND id = @id;

-- name: SkillListPage :many
SELECT id, name, slug, description, source_type, source_url, network_scope, workspace_id, created_by,
       created_at, updated_at, registry_item_id, s3_path
FROM skills
WHERE workspace_id = @workspace_id
  AND id = ANY(@ids::uuid[])
  AND (sqlc.narg(search)::text IS NULL OR name ILIKE sqlc.narg(search)::text OR description ILIKE sqlc.narg(search)::text
       OR source_url ILIKE sqlc.narg(search)::text)
  AND (sqlc.narg(source_type)::varchar IS NULL OR source_type = sqlc.narg(source_type)::varchar)
  AND (sqlc.narg(network_scope)::varchar IS NULL OR network_scope = sqlc.narg(network_scope)::varchar)
  AND (sqlc.narg(from_registry)::bool IS NULL OR (registry_item_id IS NOT NULL) = sqlc.narg(from_registry)::bool)
ORDER BY created_at DESC
OFFSET @row_offset LIMIT @row_limit;

-- name: SkillCount :one
SELECT count(id)::bigint FROM skills
WHERE workspace_id = @workspace_id
  AND id = ANY(@ids::uuid[])
  AND (sqlc.narg(search)::text IS NULL OR name ILIKE sqlc.narg(search)::text OR description ILIKE sqlc.narg(search)::text
       OR source_url ILIKE sqlc.narg(search)::text)
  AND (sqlc.narg(source_type)::varchar IS NULL OR source_type = sqlc.narg(source_type)::varchar)
  AND (sqlc.narg(network_scope)::varchar IS NULL OR network_scope = sqlc.narg(network_scope)::varchar)
  AND (sqlc.narg(from_registry)::bool IS NULL OR (registry_item_id IS NOT NULL) = sqlc.narg(from_registry)::bool);

-- name: SkillListAll :many
SELECT id, name, slug, description, source_type, source_url, network_scope, workspace_id, created_by,
       created_at, updated_at, registry_item_id, s3_path
FROM skills WHERE workspace_id = @workspace_id;

-- name: SkillLatestVersion :one
SELECT id, skill_id, s3_path, digest, reason, catalog_version, created_by, created_at
FROM skill_versions WHERE workspace_id = @workspace_id AND skill_id = @skill_id
ORDER BY created_at DESC, id DESC LIMIT 1;

-- name: SkillVersions :many
SELECT id, skill_id, s3_path, digest, reason, catalog_version, created_by, created_at
FROM skill_versions WHERE workspace_id = @workspace_id AND skill_id = @skill_id
ORDER BY created_at, id;

-- name: SkillVersionGet :one
SELECT id, skill_id, s3_path, digest, reason, catalog_version, created_by, created_at
FROM skill_versions WHERE workspace_id = @workspace_id AND skill_id = @skill_id AND id = @id;

-- name: SkillVersionInsert :exec
INSERT INTO skill_versions (id, skill_id, s3_path, digest, reason, catalog_version, workspace_id, created_by, created_at, updated_at)
VALUES (@id, @skill_id, @s3_path, sqlc.narg(digest)::varchar, @reason, sqlc.narg(catalog_version)::varchar, @workspace_id,
        @created_by, @now, @now);

-- name: SkillMembers :many
SELECT m.parent_skill_id, m.child_skill_id, m."order", m.is_required, m.dependencies
FROM skill_members m JOIN skills s ON s.id = m.child_skill_id
WHERE m.parent_skill_id = @parent_skill_id AND s.workspace_id = @workspace_id
ORDER BY m."order";

-- name: SkillMemberExists :one
SELECT EXISTS (SELECT 1 FROM skill_members WHERE parent_skill_id = @parent_skill_id AND child_skill_id = @child_skill_id)::bool;

-- name: SkillMemberUpdate :exec
UPDATE skill_members SET "order" = @member_order, is_required = @is_required, dependencies = @dependencies
WHERE parent_skill_id = @parent_skill_id AND child_skill_id = @child_skill_id;

-- name: SkillMemberInsert :exec
INSERT INTO skill_members (parent_skill_id, child_skill_id, "order", is_required, dependencies)
VALUES (@parent_skill_id, @child_skill_id, @member_order, @is_required, @dependencies);

-- name: SkillMemberDelete :execrows
DELETE FROM skill_members WHERE parent_skill_id = @parent_skill_id AND child_skill_id = @child_skill_id;

-- name: SkillsWithBodies :many
SELECT id, workspace_id FROM skills
WHERE content IS NOT NULL AND workspace_id <> @platform_workspace_id
ORDER BY workspace_id, id;

-- name: SkillsAtOwnCopies :many
SELECT id, workspace_id FROM skills
WHERE s3_path = concat('skills/', workspace_id, '/', id::text, '/')
ORDER BY workspace_id, id;

-- name: SkillMovedOwnCopies :many
SELECT concat('skills/', workspace_id, '/', id::text, '/')::text AS prefix FROM skills
WHERE id IN (SELECT v.skill_id FROM skill_versions v WHERE v.reason = 'migrate' AND v.created_at < sqlc.arg(moved_before)::timestamp)
  AND s3_path IS DISTINCT FROM concat('skills/', workspace_id, '/', id::text, '/')
ORDER BY workspace_id, id;

-- name: SkillAgentCounts :many
SELECT a.skill_id, count(*)::bigint AS agents
FROM agent_skills a JOIN agents g ON g.id = a.agent_id
WHERE g.workspace_id = @workspace_id AND g.status <> 'archived' AND a.skill_id = ANY(@ids::uuid[])
GROUP BY a.skill_id;

-- name: SkillRevisions :many
SELECT skill_id, count(*)::bigint AS revisions
FROM skill_versions
WHERE workspace_id = @workspace_id AND skill_id = ANY(@ids::uuid[])
GROUP BY skill_id;
