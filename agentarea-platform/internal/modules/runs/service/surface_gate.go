package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// PendingApprovalTTL is PENDING_TTL: how long an open request waits for a decision.
const PendingApprovalTTL = 24 * time.Hour

var _ api.HeldCalls = (*Surface)(nil)

// ArgumentsHash is arguments_hash: sha256 of the arguments as canonical JSON (sorted keys, no
// whitespace, ASCII escapes).
func ArgumentsHash(arguments map[string]any) string {
	if arguments == nil {
		arguments = map[string]any{}
	}
	sum := sha256.Sum256([]byte(domain.PyDumpsCanonical(arguments)))
	return hex.EncodeToString(sum[:])
}

// Gate is ToolCallApprovalService.gate.
func (s *Surface) Gate(ctx context.Context, tx db.Session, ws scope.Workspace, call api.HeldCall) (api.HeldOutcome, error) {
	now := s.d.Now().UTC()
	hash := ArgumentsHash(call.Arguments)
	instance := uuid.NullUUID{}
	if call.MCPInstanceID != "" {
		id, err := uuid.Parse(call.MCPInstanceID)
		if err != nil {
			return api.HeldOutcome{}, fmt.Errorf("held call: MCP instance id %q: %w", call.MCPInstanceID, err)
		}
		instance = uuid.NullUUID{UUID: id, Valid: true}
	}
	q := store.New(tx.Q())
	if err := q.GateExpireLapsed(ctx, store.GateExpireLapsedParams{
		WorkspaceID: ws.ID(), CreatedBy: call.UserID, McpInstanceID: instance, Tool: call.Tool, ArgumentsHash: hash,
		Now: store.Timestamptz(now),
	}); err != nil {
		return api.HeldOutcome{}, err
	}
	consumed, err := q.GateConsumeApproved(ctx, store.GateConsumeApprovedParams{
		WorkspaceID: ws.ID(), CreatedBy: call.UserID, McpInstanceID: instance, Tool: call.Tool, ArgumentsHash: hash,
		Now: store.Timestamptz(now),
	})
	if err == nil {
		return api.HeldOutcome{Verdict: api.HeldRun, ApprovalID: consumed.ID.String(), DecidedBy: deref(store.TextPtr(consumed.DecidedBy)),
			Comment: store.TextPtr(consumed.Comment), Connector: call.Connector, Tool: call.Tool}, nil
	}
	if !store.NoRows(err) {
		return api.HeldOutcome{}, err
	}
	find := func(status string) (api.HeldOutcome, bool, error) {
		r, err := q.GateFindLive(ctx, store.GateFindLiveParams{
			WorkspaceID: ws.ID(), CreatedBy: call.UserID, McpInstanceID: instance, Tool: call.Tool, ArgumentsHash: hash,
			Status: status, Now: store.Timestamptz(now),
		})
		if store.NoRows(err) {
			return api.HeldOutcome{}, false, nil
		}
		if err != nil {
			return api.HeldOutcome{}, false, err
		}
		return api.HeldOutcome{ApprovalID: r.ID.String(), DecidedBy: deref(store.TextPtr(r.DecidedBy)), Comment: store.TextPtr(r.Comment),
			Connector: r.Connector, Tool: r.Tool}, true, nil
	}
	if out, ok, err := find("rejected"); err != nil || ok {
		out.Verdict = api.HeldRejected
		return out, err
	}
	out, ok, err := find("pending")
	if err != nil {
		return out, err
	}
	if !ok {
		if _, err = s.createPending(ctx, q, ws, call, instance, hash, now); err != nil {
			return out, err
		}
		if out, ok, err = find("pending"); err != nil {
			return out, err
		}
		if !ok {
			return out, fmt.Errorf("no pending approval of %s could be recorded or found for %s", call.Tool, call.UserID)
		}
	}
	out.Verdict = api.HeldPending
	out.URL, err = s.approvalPageURL(ws.Slug(), out.ApprovalID)
	return out, err
}

func (s *Surface) createPending(ctx context.Context, q *store.Queries, ws scope.Workspace, call api.HeldCall, instance uuid.NullUUID, hash string, now time.Time) (bool, error) {
	args, err := json.Marshal(call.Arguments)
	if err != nil {
		return false, err
	}
	if call.Arguments == nil {
		args = []byte("{}")
	}
	approvers := call.Approvers
	if approvers == nil {
		approvers = []string{}
	}
	refs, err := json.Marshal(approvers)
	if err != nil {
		return false, err
	}
	_, err = q.GateCreatePending(ctx, store.GateCreatePendingParams{
		ID: uuid.New(), WorkspaceID: ws.ID(), CreatedBy: call.UserID, ClientID: store.Text(call.ClientID), ClientName: store.Text(call.ClientName),
		McpInstanceID: instance, Connector: call.Connector, Tool: call.Tool, PolicyName: call.PolicyName, Arguments: args,
		ArgumentsHash: hash, Reason: call.Reason, Approvers: refs, ExpiresAt: store.Timestamptz(now.Add(PendingApprovalTTL)),
		CreatedAt: store.Timestamp(now),
	})
	if store.NoRows(err) {
		return false, nil
	}
	return err == nil, err
}
