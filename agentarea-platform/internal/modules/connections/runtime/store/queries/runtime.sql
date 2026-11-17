-- name: LoadInstance :one
SELECT id::text AS instance_id, name, transport, json_spec, server_spec_id, workspace_id, auth_config_id, managed_by
FROM mcp_server_instances
WHERE id = $1;

-- name: MarkStarting :execrows
INSERT INTO mcp_runtime_instances (instance_id, generation, state, last_used_at, updated_at)
VALUES ($1, 1, 'starting', now(), now())
ON CONFLICT (instance_id) DO UPDATE
SET generation = mcp_runtime_instances.generation + 1, state = 'starting', last_error = NULL, updated_at = now()
WHERE mcp_runtime_instances.state NOT IN ('ready', 'starting');

-- name: StateForUpdate :one
SELECT state FROM mcp_runtime_instances WHERE instance_id = $1 FOR UPDATE;

-- name: SetReady :execrows
UPDATE mcp_runtime_instances SET state = 'ready', last_used_at = now(), last_error = NULL, updated_at = now()
WHERE instance_id = $1;

-- name: BeginLease :exec
INSERT INTO mcp_runtime_request_leases (request_id, instance_id, expires_at)
VALUES (@request_id, @instance_id, now() + make_interval(secs => @ttl_seconds::float8));

-- name: HeartbeatLease :execrows
UPDATE mcp_runtime_request_leases SET expires_at = now() + make_interval(secs => @ttl_seconds::float8)
WHERE request_id = @request_id;

-- name: FinishLease :execrows
DELETE FROM mcp_runtime_request_leases WHERE request_id = $1 AND instance_id = $2;

-- name: TouchUsed :exec
UPDATE mcp_runtime_instances SET last_used_at = now(), updated_at = now() WHERE instance_id = $1;

-- name: DeleteExpiredLeases :exec
DELETE FROM mcp_runtime_request_leases WHERE expires_at <= now();

-- name: IdleCandidates :many
SELECT r.instance_id
FROM mcp_runtime_instances r
JOIN mcp_server_instances i ON i.id = r.instance_id
WHERE ((r.state = 'ready' AND r.last_used_at < now() - make_interval(secs => @idle_seconds::float8))
    OR (r.state IN ('starting', 'failed') AND r.updated_at < now() - make_interval(secs => @idle_seconds::float8)))
  AND i.transport IN ('docker', 'command')
  AND NOT EXISTS (SELECT 1 FROM mcp_runtime_request_leases l WHERE l.instance_id = r.instance_id AND l.expires_at > now());

-- name: IdleEligible :one
SELECT EXISTS (
  SELECT 1 FROM mcp_runtime_instances r
  WHERE r.instance_id = @instance_id
    AND ((r.state = 'ready' AND r.last_used_at < now() - make_interval(secs => @idle_seconds::float8))
      OR (r.state IN ('starting', 'failed') AND r.updated_at < now() - make_interval(secs => @idle_seconds::float8)))
    AND NOT EXISTS (SELECT 1 FROM mcp_runtime_request_leases l WHERE l.instance_id = r.instance_id AND l.expires_at > now())
);

-- name: InstanceState :one
SELECT state FROM mcp_runtime_instances WHERE instance_id = $1;

-- name: LiveLeaseExists :one
SELECT EXISTS (SELECT 1 FROM mcp_runtime_request_leases WHERE instance_id = $1 AND expires_at > now());

-- name: BeginRetirement :exec
INSERT INTO mcp_runtime_instances (instance_id, generation, state, last_used_at, updated_at)
VALUES ($1, 1, 'reaping', now(), now())
ON CONFLICT (instance_id) DO UPDATE SET state = 'reaping', updated_at = now();

-- name: SetState :exec
UPDATE mcp_runtime_instances SET state = @state, last_error = NULLIF(@last_error::text, ''), updated_at = now()
WHERE instance_id = @instance_id;

-- name: LifecycleRow :one
SELECT i.workspace_id, r.generation, r.state, r.updated_at
FROM mcp_runtime_instances r
JOIN mcp_server_instances i ON i.id = r.instance_id
WHERE r.instance_id = $1;

-- name: CountByState :many
SELECT state, count(*)::bigint AS n FROM mcp_runtime_instances GROUP BY state;
