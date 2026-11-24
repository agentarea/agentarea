-- Reads connections makes of agents and clients.

-- name: LocateClient :one
SELECT workspace_id FROM clients WHERE id = @id AND workspace_id = ANY(@workspaces::text[]);
