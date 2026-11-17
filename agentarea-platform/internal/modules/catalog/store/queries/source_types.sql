-- name: SourceTypeRows :many
SELECT external_id, spec FROM registry_items
WHERE registry_type = 'source_types' AND registry_active
ORDER BY registry_priority, recommendation_rank, name;

-- name: SourceTypeRowsBySlug :many
SELECT external_id, spec FROM registry_items
WHERE registry_type = 'source_types' AND registry_active AND external_id = @slug
ORDER BY registry_priority;
