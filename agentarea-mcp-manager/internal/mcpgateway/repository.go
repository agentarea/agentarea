package mcpgateway

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	_ "github.com/jackc/pgx/v5/stdlib"
)

var ErrInstanceNotFound = errors.New("MCP instance not found")
var ErrInstanceBusy = errors.New("MCP instance has active requests")

const (
	maxGatewayDatabaseConns     = 16
	maxGatewayIdleDatabaseConns = 4
	gatewayDatabaseConnLifetime = 30 * time.Minute
)

type SQLRepository struct {
	db *sql.DB
}

func OpenSQLRepository(ctx context.Context, dsn string) (*SQLRepository, error) {
	if dsn == "" {
		return nil, fmt.Errorf("MCP gateway database DSN is required")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, fmt.Errorf("open MCP gateway database: %w", err)
	}
	// Every activation holds one connection for the whole lifecycle section,
	// which can last up to the startup timeout. Left unbounded, a burst of MCP
	// tool calls would open a connection each and exhaust the Postgres shared
	// with the API and the worker. Capping here makes the overload surface as
	// slow activations on this one component instead of taking down the others.
	db.SetMaxOpenConns(maxGatewayDatabaseConns)
	db.SetMaxIdleConns(maxGatewayIdleDatabaseConns)
	db.SetConnMaxLifetime(gatewayDatabaseConnLifetime)
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, fmt.Errorf("connect MCP gateway database: %w", err)
	}
	if _, err := db.ExecContext(ctx, `
SELECT runtime.instance_id, lease.request_id
FROM mcp_runtime_instances runtime
LEFT JOIN mcp_runtime_request_leases lease ON lease.instance_id = runtime.instance_id
LIMIT 0
`); err != nil {
		db.Close()
		return nil, fmt.Errorf("MCP gateway runtime schema is unavailable; run database migrations: %w", err)
	}
	return &SQLRepository{db: db}, nil
}

func (r *SQLRepository) Close() error { return r.db.Close() }

func (r *SQLRepository) WithInstanceLock(ctx context.Context, instanceID string, callback func(context.Context) error) error {
	conn, err := r.db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctx, `SELECT pg_advisory_lock(hashtextextended($1, 0))`, instanceID); err != nil {
		return fmt.Errorf("lock MCP instance lifecycle: %w", err)
	}
	defer func() {
		_, _ = conn.ExecContext(context.Background(), `SELECT pg_advisory_unlock(hashtextextended($1, 0))`, instanceID)
	}()
	return callback(ctx)
}

func (r *SQLRepository) LoadInstance(ctx context.Context, instanceID string) (*models.MCPServerInstance, error) {
	var id, name string
	var instanceJSON, serverJSON, commandJSON []byte
	var dockerImage, remoteURL sql.NullString
	// The two json_spec columns have different types — mcp_server_instances.json_spec
	// is json, mcp_servers.json_spec is jsonb — so each COALESCE has to match its
	// own column. Defaulting both to ::json makes Postgres reject the whole query.
	err := r.db.QueryRowContext(ctx, `
SELECT i.id::text, i.name, i.json_spec, COALESCE(s.json_spec, '{}'::jsonb),
       s.docker_image_url, s.remote_url, COALESCE(s.cmd, 'null'::json)
FROM mcp_server_instances i
JOIN mcp_servers s ON s.id::text = i.server_spec_id
WHERE i.id = $1::uuid
`, instanceID).Scan(&id, &name, &instanceJSON, &serverJSON, &dockerImage, &remoteURL, &commandJSON)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrInstanceNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("load MCP instance: %w", err)
	}
	serverSpec := map[string]any{}
	instanceSpec := map[string]any{}
	if err := json.Unmarshal(serverJSON, &serverSpec); err != nil {
		return nil, fmt.Errorf("decode MCP server spec: %w", err)
	}
	if err := json.Unmarshal(instanceJSON, &instanceSpec); err != nil {
		return nil, fmt.Errorf("decode MCP instance spec: %w", err)
	}
	for key, value := range instanceSpec {
		serverSpec[key] = value
	}
	if remoteURL.Valid && remoteURL.String != "" {
		serverSpec["type"] = "url"
		serverSpec["endpoint_url"] = remoteURL.String
	} else if string(commandJSON) != "null" {
		var command []string
		if err := json.Unmarshal(commandJSON, &command); err != nil || len(command) == 0 {
			return nil, fmt.Errorf("decode MCP command spec")
		}
		serverSpec["type"] = "command"
		serverSpec["command"] = command[0]
		args := make([]any, 0, len(command)-1)
		for _, item := range command[1:] {
			args = append(args, item)
		}
		serverSpec["args"] = args
	} else if dockerImage.Valid && dockerImage.String != "" {
		if _, exists := serverSpec["type"]; !exists {
			serverSpec["type"] = "docker"
		}
		if _, exists := serverSpec["image"]; !exists {
			serverSpec["image"] = dockerImage.String
		}
	}
	instanceType, _ := serverSpec["type"].(string)
	if instanceType != "docker" && instanceType != "command" && instanceType != "kubernetes" {
		return nil, fmt.Errorf("instance %s is not a container-backed MCP server", id)
	}
	// Runtime object names are identity-derived. The user-facing display name
	// remains in Postgres and never participates in data-plane addressing.
	return &models.MCPServerInstance{InstanceID: id, Name: id, JSONSpec: serverSpec}, nil
}

// MarkStarting opens an activation. An instance that is already ready stays
// ready: the overwhelming majority of requests are warm, and flipping a serving
// instance to 'starting' on every call both misreports its state and makes
// generation a count of requests rather than of workload generations.
func (r *SQLRepository) MarkStarting(ctx context.Context, instanceID string) error {
	_, err := r.db.ExecContext(ctx, `
INSERT INTO mcp_runtime_instances(instance_id, generation, state, last_used_at, updated_at)
VALUES ($1::uuid, 1, 'starting', now(), now())
ON CONFLICT (instance_id) DO UPDATE
SET generation = CASE WHEN mcp_runtime_instances.state = 'ready'
                      THEN mcp_runtime_instances.generation
                      ELSE mcp_runtime_instances.generation + 1 END,
    state = CASE WHEN mcp_runtime_instances.state = 'ready' THEN 'ready' ELSE 'starting' END,
    last_error = NULL,
    updated_at = now()
`, instanceID)
	return err
}

func (r *SQLRepository) MarkFailed(ctx context.Context, instanceID string, cause error) error {
	_, err := r.db.ExecContext(ctx, `UPDATE mcp_runtime_instances SET state='failed', last_error=$2, updated_at=now() WHERE instance_id=$1::uuid`, instanceID, cause.Error())
	return err
}

func (r *SQLRepository) MarkReadyAndBeginRequest(ctx context.Context, instanceID, requestID string, ttl time.Duration) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	result, err := tx.ExecContext(ctx, `UPDATE mcp_runtime_instances SET state='ready', last_used_at=now(), last_error=NULL, updated_at=now() WHERE instance_id=$1::uuid`, instanceID)
	if err != nil {
		return err
	}
	affected, err := result.RowsAffected()
	if err != nil || affected != 1 {
		return fmt.Errorf("MCP runtime ownership was lost before request admission")
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO mcp_runtime_request_leases(request_id, instance_id, expires_at) VALUES ($1::uuid, $2::uuid, now() + make_interval(secs => $3))`, requestID, instanceID, ttl.Seconds()); err != nil {
		return err
	}
	return tx.Commit()
}

func (r *SQLRepository) HeartbeatRequest(ctx context.Context, requestID string, ttl time.Duration) error {
	result, err := r.db.ExecContext(ctx, `UPDATE mcp_runtime_request_leases SET expires_at=now() + make_interval(secs => $2) WHERE request_id=$1::uuid`, requestID, ttl.Seconds())
	if err != nil {
		return err
	}
	affected, err := result.RowsAffected()
	if err != nil || affected != 1 {
		return fmt.Errorf("MCP request lease ownership was lost")
	}
	return nil
}

func (r *SQLRepository) FinishRequest(ctx context.Context, instanceID, requestID string) error {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	result, err := tx.ExecContext(ctx, `DELETE FROM mcp_runtime_request_leases WHERE request_id=$1::uuid AND instance_id=$2::uuid`, requestID, instanceID)
	if err != nil {
		return err
	}
	affected, err := result.RowsAffected()
	if err != nil || affected != 1 {
		return fmt.Errorf("MCP request lease ownership was lost before finalization")
	}
	if _, err := tx.ExecContext(ctx, `UPDATE mcp_runtime_instances SET last_used_at=now(), updated_at=now() WHERE instance_id=$1::uuid`, instanceID); err != nil {
		return err
	}
	return tx.Commit()
}

func (r *SQLRepository) IdleCandidates(ctx context.Context, idleTimeout time.Duration) ([]string, error) {
	if _, err := r.db.ExecContext(ctx, `DELETE FROM mcp_runtime_request_leases WHERE expires_at <= now()`); err != nil {
		return nil, err
	}
	// Selecting only 'ready' would strand any workload whose cold start died
	// after CreateInstance but before it was marked ready — and whose cleanup
	// also failed. Such a row never reaches 'ready', so reclamation would be
	// structurally unreachable and the workload would run until someone called
	// that instance again. 'starting' and 'failed' are therefore reclaimable
	// once they have been untouched for the same idle window, measured on
	// updated_at because they have no meaningful last use.
	rows, err := r.db.QueryContext(ctx, `
SELECT runtime.instance_id::text
FROM mcp_runtime_instances runtime
JOIN mcp_server_instances instance ON instance.id = runtime.instance_id
JOIN mcp_servers server ON server.id::text = instance.server_spec_id
WHERE (
        (runtime.state = 'ready' AND runtime.last_used_at < now() - make_interval(secs => $1))
     OR (runtime.state IN ('starting','failed') AND runtime.updated_at < now() - make_interval(secs => $1))
      )
	  AND COALESCE(instance.json_spec->>'type', server.json_spec->>'type', CASE WHEN server.remote_url IS NOT NULL THEN 'url' WHEN server.cmd IS NOT NULL THEN 'command' ELSE 'docker' END) IN ('docker','command','kubernetes')
  AND NOT EXISTS (
    SELECT 1 FROM mcp_runtime_request_leases lease
    WHERE lease.instance_id = runtime.instance_id AND lease.expires_at > now()
  )
`, idleTimeout.Seconds())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

func (r *SQLRepository) ReapIfIdle(ctx context.Context, instanceID string, idleTimeout time.Duration, remove func(context.Context, *models.MCPServerInstance) error) (bool, error) {
	removed := false
	err := r.WithInstanceLock(ctx, instanceID, func(lockCtx context.Context) error {
		var eligible bool
		// Must mirror IdleCandidates exactly, including stranded cold starts —
		// a narrower re-check here would select a row and then always decline it.
		if err := r.db.QueryRowContext(lockCtx, `
SELECT EXISTS(
  SELECT 1 FROM mcp_runtime_instances runtime
  WHERE runtime.instance_id=$1::uuid
    AND (
          (runtime.state='ready' AND runtime.last_used_at < now() - make_interval(secs => $2))
       OR (runtime.state IN ('starting','failed') AND runtime.updated_at < now() - make_interval(secs => $2))
        )
    AND NOT EXISTS (SELECT 1 FROM mcp_runtime_request_leases lease WHERE lease.instance_id=runtime.instance_id AND lease.expires_at>now())
)
`, instanceID, idleTimeout.Seconds()).Scan(&eligible); err != nil || !eligible {
			return err
		}
		instance, err := r.LoadInstance(lockCtx, instanceID)
		if err != nil {
			return err
		}
		// Remember the state being reaped so a failed teardown restores the
		// truth. Forcing 'ready' here would claim a stranded cold start is
		// serving requests, and would also hide it from the next sweep.
		// Read then write: the advisory lock is held, so nothing can change the
		// state in between, and the two steps stay obvious.
		var previousState string
		if err := r.db.QueryRowContext(lockCtx,
			`SELECT state FROM mcp_runtime_instances WHERE instance_id=$1::uuid`,
			instanceID).Scan(&previousState); err != nil {
			return err
		}
		if _, err := r.db.ExecContext(lockCtx,
			`UPDATE mcp_runtime_instances SET state='reaping', updated_at=now() WHERE instance_id=$1::uuid`,
			instanceID); err != nil {
			return err
		}
		if err := remove(lockCtx, instance); err != nil {
			_, _ = r.db.ExecContext(lockCtx,
				`UPDATE mcp_runtime_instances SET state=$3, last_error=$2, updated_at=now() WHERE instance_id=$1::uuid`,
				instanceID, err.Error(), previousState)
			return err
		}
		if _, err := r.db.ExecContext(lockCtx, `UPDATE mcp_runtime_instances SET state='dormant', last_error=NULL, updated_at=now() WHERE instance_id=$1::uuid`, instanceID); err != nil {
			return err
		}
		removed = true
		return nil
	})
	return removed, err
}

func (r *SQLRepository) RetireForDeletion(ctx context.Context, instanceID string, remove func(context.Context, *models.MCPServerInstance) error) error {
	return r.WithInstanceLock(ctx, instanceID, func(lockCtx context.Context) error {
		instance, err := r.LoadInstance(lockCtx, instanceID)
		if err != nil {
			return err
		}
		var active bool
		if err := r.db.QueryRowContext(lockCtx, `
SELECT EXISTS(
  SELECT 1 FROM mcp_runtime_request_leases
  WHERE instance_id=$1::uuid AND expires_at>now()
)
`, instanceID).Scan(&active); err != nil {
			return err
		}
		if active {
			return ErrInstanceBusy
		}
		if _, err := r.db.ExecContext(lockCtx, `
INSERT INTO mcp_runtime_instances(instance_id, generation, state, last_used_at, updated_at)
VALUES ($1::uuid, 1, 'reaping', now(), now())
ON CONFLICT (instance_id) DO UPDATE SET generation=mcp_runtime_instances.generation+1, state='reaping', updated_at=now()
`, instanceID); err != nil {
			return err
		}
		if err := remove(lockCtx, instance); err != nil {
			_, _ = r.db.ExecContext(lockCtx, `UPDATE mcp_runtime_instances SET state='failed', last_error=$2, updated_at=now() WHERE instance_id=$1::uuid`, instanceID, err.Error())
			return err
		}
		_, err = r.db.ExecContext(lockCtx, `UPDATE mcp_runtime_instances SET state='dormant', last_error=NULL, updated_at=now() WHERE instance_id=$1::uuid`, instanceID)
		return err
	})
}
