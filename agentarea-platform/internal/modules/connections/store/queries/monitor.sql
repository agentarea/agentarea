-- The monitor's and the dispatch stamps' writes span workspaces.

-- name: StampLastDispatch :execrows
UPDATE mcp_server_instances SET last_dispatch = @last_dispatch WHERE id = @id;

-- name: ListPackageImportCandidates :many
SELECT id, workspace_id, server_spec_id, json_spec, managed_by FROM mcp_server_instances
WHERE transport = 'command'
  AND verification->>'status' = 'succeeded'
  AND (json_spec->'package_import' IS NULL
       OR (json_spec->'package_import'->>'status' = 'unavailable'
           AND (json_spec->'package_import'->>'at')::timestamptz < @before::timestamptz))
ORDER BY created_at, id
LIMIT @max_rows::int;

-- name: LockInstanceForImport :one
SELECT id, workspace_id, server_spec_id, transport, json_spec, managed_by
FROM mcp_server_instances WHERE id = @id FOR UPDATE;

-- name: SetImportedSpec :execrows
UPDATE mcp_server_instances
SET json_spec = @json_spec, transport = @transport, updated_at = @now
WHERE id = @id;
