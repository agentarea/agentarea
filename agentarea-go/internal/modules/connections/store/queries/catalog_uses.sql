-- name: MoveOpenAPIConnectionItems :execrows
UPDATE openapi_connections SET registry_item_id = @new_id::uuid WHERE registry_item_id = @old_id::uuid;

-- name: MoveMCPInstanceSpecs :execrows
UPDATE mcp_server_instances SET server_spec_id = @new_spec::text WHERE server_spec_id = @old_spec::text;

-- name: OpenAPIReferencedItems :many
SELECT DISTINCT registry_item_id::uuid FROM openapi_connections WHERE registry_item_id = ANY(@ids::uuid[]);
