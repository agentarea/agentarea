-- Writes and full reads of openapi_connections. Writes assert the strict
-- workspace filter: a platform-managed row is never written from a workspace.

-- name: InsertOpenAPIConnection :one
INSERT INTO openapi_connections (
    id, workspace_id, created_by, name, description, spec_url, spec_content, base_url,
    auth_config_id, registry_item_id, allowed_auth_origins, custom_headers, custom_query_params,
    url_variables, available_tools, status, created_at, updated_at
) VALUES (
    @id, @workspace_id, @created_by, @name, sqlc.narg('description'), sqlc.narg('spec_url'),
    sqlc.narg('spec_content'), @base_url, sqlc.narg('auth_config_id'), sqlc.narg('registry_item_id'),
    sqlc.narg('allowed_auth_origins'), sqlc.narg('custom_headers'), sqlc.narg('custom_query_params'),
    sqlc.narg('url_variables'), @available_tools, @status, @now, @now
)
RETURNING id, workspace_id, created_by, name, description, spec_url, base_url, auth_config_id,
          registry_item_id, custom_headers, custom_query_params, url_variables, available_tools,
          status, last_dispatch, managed_by, cost, created_at, updated_at,
          spec_content, allowed_auth_origins;

-- name: GetOpenAPIConnectionFull :one
SELECT id, workspace_id, created_by, name, description, spec_url, base_url, auth_config_id,
       registry_item_id, custom_headers, custom_query_params, url_variables, available_tools,
       status, last_dispatch, managed_by, cost, created_at, updated_at,
       spec_content, allowed_auth_origins
FROM openapi_connections
WHERE id = @id AND (workspace_id = @workspace_id OR managed_by = 'platform');

-- name: LockOpenAPIConnection :one
SELECT id, workspace_id, created_by, name, description, spec_url, base_url, auth_config_id,
       registry_item_id, custom_headers, custom_query_params, url_variables, available_tools,
       status, last_dispatch, managed_by, cost, created_at, updated_at,
       spec_content, allowed_auth_origins
FROM openapi_connections
WHERE id = @id AND workspace_id = @workspace_id
FOR UPDATE;

-- name: UpdateOpenAPIConnection :execrows
UPDATE openapi_connections
SET name = @name, description = sqlc.narg('description'), spec_url = sqlc.narg('spec_url'),
    spec_content = sqlc.narg('spec_content'), base_url = @base_url,
    auth_config_id = sqlc.narg('auth_config_id'), custom_headers = sqlc.narg('custom_headers'),
    custom_query_params = sqlc.narg('custom_query_params'), url_variables = sqlc.narg('url_variables'),
    available_tools = @available_tools, cost = sqlc.narg('cost'), updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- name: SetOpenAPIDiscovery :execrows
UPDATE openapi_connections
SET available_tools = @available_tools, spec_content = sqlc.narg('spec_content'), updated_at = @now
WHERE id = @id AND workspace_id = @workspace_id;

-- record_dispatch: the last successful call, updated_at untouched.
-- name: SetOpenAPILastDispatch :execrows
UPDATE openapi_connections
SET last_dispatch = @last_dispatch
WHERE id = @id AND workspace_id = @workspace_id;
