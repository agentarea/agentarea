-- name: ListOpenAPIConnections :many
SELECT id, workspace_id, created_by, name, description, spec_url, base_url, auth_config_id,
       registry_item_id, custom_headers, custom_query_params, url_variables, available_tools,
       status, last_dispatch, managed_by, cost, created_at, updated_at
FROM openapi_connections
WHERE (workspace_id = @workspace_id OR managed_by = 'platform')
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('pattern')::text IS NULL
       OR name ILIKE sqlc.narg('pattern')::text
       OR description ILIKE sqlc.narg('pattern')::text)
ORDER BY created_at DESC, id
LIMIT @page_limit::int OFFSET @page_offset::int;

-- name: GetOpenAPIConnection :one
SELECT id, workspace_id, created_by, name, description, spec_url, base_url, auth_config_id,
       registry_item_id, custom_headers, custom_query_params, url_variables, available_tools,
       status, last_dispatch, managed_by, cost, created_at, updated_at
FROM openapi_connections
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: DeleteOpenAPIConnection :execrows
DELETE FROM openapi_connections WHERE id = @id AND workspace_id = @workspace_id;
