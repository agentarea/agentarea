-- name: InsertClient :exec
INSERT INTO clients (id, created_at, updated_at, workspace_id, created_by, name, description, kind, allow_domains, sandbox)
VALUES (@id, @now, @now, @workspace_id, @created_by, @name, @description, @kind, '[]'::jsonb, true);

-- name: GetClient :one
SELECT id, workspace_id, created_by, name, description, kind, models, default_model, allow_domains, sandbox
FROM clients WHERE workspace_id = @workspace_id AND id = @id;

-- name: ListClients :many
SELECT id, workspace_id, created_by, name, description, kind, models, default_model, allow_domains, sandbox
FROM clients
WHERE workspace_id = @workspace_id AND id = ANY(@ids::uuid[])
ORDER BY created_at DESC, id
OFFSET @row_offset LIMIT @row_limit;

-- name: UpdateClient :exec
UPDATE clients SET name = @name, description = @description, kind = @kind, default_model = @default_model,
    allow_domains = @allow_domains, sandbox = @sandbox, updated_at = @now
WHERE workspace_id = @workspace_id AND id = @id;

-- name: DeleteClient :execrows
DELETE FROM clients WHERE workspace_id = @workspace_id AND id = @id;

-- name: CountClientAgents :one
SELECT count(*)::bigint FROM agents WHERE workspace_id = @workspace_id AND client_id = @client_id;

-- name: ClientSkillLinks :many
SELECT cs.client_id, s.id, s.name
FROM client_skills cs
JOIN clients c ON c.id = cs.client_id
JOIN skills s ON s.id = cs.skill_id
WHERE c.workspace_id = @workspace_id AND s.workspace_id = @workspace_id AND cs.client_id = ANY(@ids::uuid[]);

-- name: ClientMCPInstanceLinks :many
SELECT l.client_id, l.mcp_instance_id, l.namespace_prefix, l.allowed_tools
FROM client_mcp_instances l
JOIN clients c ON c.id = l.client_id
WHERE c.workspace_id = @workspace_id AND l.client_id = ANY(@ids::uuid[]);

-- name: ClientOpenAPILinks :many
SELECT l.client_id, l.openapi_connection_id, l.namespace_prefix, l.allowed_tools
FROM client_openapi_connections l
JOIN clients c ON c.id = l.client_id
WHERE c.workspace_id = @workspace_id AND l.client_id = ANY(@ids::uuid[]);

-- name: ClientPlatformToolsetLinks :many
SELECT l.client_id, l.toolset, l.disabled_methods
FROM client_platform_toolsets l
JOIN clients c ON c.id = l.client_id
WHERE c.workspace_id = @workspace_id AND l.client_id = ANY(@ids::uuid[])
ORDER BY l.toolset;

-- name: AddClientSkill :exec
INSERT INTO client_skills (client_id, skill_id) VALUES (@client_id, @skill_id) ON CONFLICT DO NOTHING;

-- name: RemoveClientSkill :exec
DELETE FROM client_skills WHERE client_id = @client_id AND skill_id = @skill_id;

-- name: SetClientMCPInstance :exec
INSERT INTO client_mcp_instances (client_id, mcp_instance_id, namespace_prefix, allowed_tools)
VALUES (@client_id, @mcp_instance_id, @namespace_prefix, @allowed_tools)
ON CONFLICT (client_id, mcp_instance_id) DO UPDATE
SET namespace_prefix = EXCLUDED.namespace_prefix, allowed_tools = EXCLUDED.allowed_tools;

-- name: RemoveClientMCPInstance :exec
DELETE FROM client_mcp_instances WHERE client_id = @client_id AND mcp_instance_id = @mcp_instance_id;

-- name: SetClientOpenAPIConnection :exec
INSERT INTO client_openapi_connections (client_id, openapi_connection_id, namespace_prefix, allowed_tools)
VALUES (@client_id, @openapi_connection_id, @namespace_prefix, @allowed_tools)
ON CONFLICT (client_id, openapi_connection_id) DO UPDATE
SET namespace_prefix = EXCLUDED.namespace_prefix, allowed_tools = EXCLUDED.allowed_tools;

-- name: RemoveClientOpenAPIConnection :exec
DELETE FROM client_openapi_connections WHERE client_id = @client_id AND openapi_connection_id = @openapi_connection_id;

-- name: SetClientPlatformToolset :exec
INSERT INTO client_platform_toolsets (client_id, toolset, disabled_methods)
VALUES (@client_id, @toolset, @disabled_methods)
ON CONFLICT (client_id, toolset) DO UPDATE SET disabled_methods = EXCLUDED.disabled_methods;

-- name: RemoveClientPlatformToolset :exec
DELETE FROM client_platform_toolsets WHERE client_id = @client_id AND toolset = @toolset;
