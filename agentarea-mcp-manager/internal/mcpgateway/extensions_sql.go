package mcpgateway

import (
	"context"
	"database/sql"
	"fmt"
)

// TxStatements lets a trusted participant add statements to the lifecycle
// transaction. It deliberately has no Commit or Rollback: the repository owns
// the transaction lifetime. It is an infrastructure capability, not a security
// boundary; a participant must only write its own tables.
type TxStatements interface {
	ExecContext(context.Context, string, ...any) (sql.Result, error)
	QueryRowContext(context.Context, string, ...any) *sql.Row
}

// LifecycleParticipant writes inside the transition's transaction. Its error
// rolls back the transition and the request lease with it. It must not retain
// the statements or use them from another goroutine.
type LifecycleParticipant interface {
	BeforeCommit(context.Context, TxStatements, LifecycleChange) error
}

// SetLifecycleParticipant must be called before the repository is used.
func (r *SQLRepository) SetLifecycleParticipant(participant LifecycleParticipant) {
	r.participant = participant
}

type txStatements struct{ tx *sql.Tx }

func (s txStatements) ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error) {
	return s.tx.ExecContext(ctx, query, args...)
}

func (s txStatements) QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row {
	return s.tx.QueryRowContext(ctx, query, args...)
}

// beforeLifecycleCommit reads the row as this transaction will commit it, so
// the participant never has to query core tables to reconstruct the change.
func (r *SQLRepository) beforeLifecycleCommit(ctx context.Context, tx *sql.Tx, instanceID string, transition Transition, reason string) error {
	if r.participant == nil {
		return nil
	}
	change := LifecycleChange{InstanceID: instanceID, Transition: transition, Reason: reason}
	if err := tx.QueryRowContext(ctx, `
SELECT instance.workspace_id, runtime.generation, runtime.state, runtime.updated_at
FROM mcp_runtime_instances runtime
JOIN mcp_server_instances instance ON instance.id=runtime.instance_id
WHERE runtime.instance_id=$1::uuid`, instanceID).Scan(&change.WorkspaceID, &change.Generation, &change.State, &change.UpdatedAt); err != nil {
		return err
	}
	if err := r.participant.BeforeCommit(ctx, txStatements{tx: tx}, change); err != nil {
		return fmt.Errorf("MCP lifecycle %s participant for instance %s: %w", transition, instanceID, err)
	}
	return nil
}
