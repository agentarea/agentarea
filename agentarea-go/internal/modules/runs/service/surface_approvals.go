package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

// approvedTTL is APPROVED_TTL: how long an approval may be used.
const approvedTTL = time.Hour

// Approval is a ToolCallApproval as _to_approval reads it.
type Approval struct {
	ID, RequestedBy, Connector, Tool, PolicyName, Status, Reason string
	ClientID, ClientName, MCPInstanceID, DecidedBy, Comment      *string
	Arguments                                                    any
	Approvers                                                    []string
	DecidedAt                                                    *time.Time
	ExpiresAt, CreatedAt                                         time.Time
}

func approvalOf(r store.SurfaceApprovalRow, now time.Time) (Approval, error) {
	a := Approval{
		ID: r.ID.String(), RequestedBy: r.CreatedBy, Connector: r.Connector, Tool: r.Tool, PolicyName: r.PolicyName,
		Status: r.Status, Reason: r.Reason, ClientID: store.TextPtr(r.ClientID), ClientName: store.TextPtr(r.ClientName),
		MCPInstanceID: uuidPtr(r.McpInstanceID), DecidedBy: store.TextPtr(r.DecidedBy), Comment: store.TextPtr(r.Comment),
		DecidedAt: store.TimestamptzPtr(r.DecidedAt),
	}
	if r.ExpiresAt.Valid {
		a.ExpiresAt = r.ExpiresAt.Time.UTC()
	}
	if r.CreatedAt.Valid {
		a.CreatedAt = r.CreatedAt.Time.UTC()
	}
	args, err := wirejson.Unmarshal([]byte(r.Arguments))
	if err != nil {
		return a, fmt.Errorf("arguments of approval %s: %w", a.ID, err)
	}
	a.Arguments = args
	if err := json.Unmarshal([]byte(r.Approvers), &a.Approvers); err != nil {
		return a, fmt.Errorf("approvers of approval %s: %w", a.ID, err)
	}
	if (a.Status == "pending" || a.Status == "approved") && !a.ExpiresAt.After(now) {
		a.Status = "expired"
	}
	return a, nil
}

// approvalPageURL is approval_page_url; an unset AGENTAREA_APP_URL fails as Python's RuntimeError does.
func (s *Surface) approvalPageURL(slug, id string) (string, error) {
	base := strings.TrimRight(s.d.AppURL, "/")
	if base == "" {
		return "", errors.New("AGENTAREA_APP_URL is not set: an approval link has no page to point at")
	}
	return base + "/w/" + slug + "/approve/" + id, nil
}

// ToolHints is _tool_hint: "destructive", "read-only" or nil for the tool
// of an MCP instance, nil when the instance or tool is gone.
type ToolHints interface {
	ToolHint(ctx context.Context, ws scope.Workspace, mcpInstanceID, tool string) (*string, error)
}

func (s *Surface) hint(ctx context.Context, ws scope.Workspace, a Approval) (any, error) {
	if s.d.ToolHints == nil || a.MCPInstanceID == nil {
		return nil, nil
	}
	h, err := s.d.ToolHints.ToolHint(ctx, ws, *a.MCPInstanceID, a.Tool)
	if err != nil || h == nil {
		return nil, err
	}
	return *h, nil
}

// approvalJSON is ToolCallApprovalResponse; the list answers every hint null, as Python does.
func (s *Surface) approvalJSON(c authn.Caller, a Approval, hint any) (wirejson.Object, error) {
	url, err := s.approvalPageURL(c.Workspace.Slug(), a.ID)
	if err != nil {
		return nil, err
	}
	mayDecide := callerCanApprove(c, a.Approvers)
	var args any
	if mayDecide || a.RequestedBy == c.UserID {
		args = a.Arguments
	}
	return wirejson.Object{
		{Key: "id", Value: a.ID},
		{Key: "status", Value: a.Status},
		{Key: "requested_by", Value: a.RequestedBy},
		{Key: "client_id", Value: strOrNil(a.ClientID)},
		{Key: "client_name", Value: strOrNil(a.ClientName)},
		{Key: "mcp_instance_id", Value: strOrNil(a.MCPInstanceID)},
		{Key: "connector", Value: a.Connector},
		{Key: "tool", Value: a.Tool},
		{Key: "policy_name", Value: a.PolicyName},
		{Key: "arguments", Value: args},
		{Key: "reason", Value: a.Reason},
		{Key: "hint", Value: hint},
		{Key: "can_decide", Value: a.Status == "pending" && mayDecide},
		{Key: "decided_by", Value: strOrNil(a.DecidedBy)},
		{Key: "decided_at", Value: isoOrNil(a.DecidedAt)},
		{Key: "comment", Value: strOrNil(a.Comment)},
		{Key: "expires_at", Value: PyISO(a.ExpiresAt, true)},
		{Key: "created_at", Value: PyISO(a.CreatedAt, true)},
		{Key: "url", Value: url},
	}, nil
}

// ListApprovals is list_tool_call_approvals.
func (s *Surface) ListApprovals(ctx context.Context, status *string, page, pageSize int) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	now := s.d.Now().UTC()
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	q := store.New(sess.Q())
	st := store.Text(status)
	rows, err := q.SurfaceApprovalPage(ctx, store.SurfaceApprovalPageParams{
		WorkspaceID: c.Workspace.ID(), Status: st, Now: store.Timestamptz(now), Skip: int32((page - 1) * pageSize), MaxRows: int32(pageSize),
	})
	if err != nil {
		return nil, err
	}
	total, err := q.SurfaceApprovalCount(ctx, store.SurfaceApprovalCountParams{WorkspaceID: c.Workspace.ID(), Status: st, Now: store.Timestamptz(now)})
	if err != nil {
		return nil, err
	}
	items := make([]any, len(rows))
	for i, r := range rows {
		a, err := approvalOf(store.SurfaceApprovalRow(r), now)
		if err != nil {
			return nil, err
		}
		if items[i], err = s.approvalJSON(c, a, nil); err != nil {
			return nil, err
		}
	}
	return wirejson.Object{
		{Key: "items", Value: items}, {Key: "total", Value: total}, {Key: "page", Value: page}, {Key: "page_size", Value: pageSize},
	}, nil
}

func (s *Surface) approval(ctx context.Context, sess db.Session, id string, now time.Time) (Approval, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return Approval{}, false, nil
	}
	r, err := store.New(sess.Q()).SurfaceApproval(ctx, store.SurfaceApprovalParams{ID: u, WorkspaceID: sess.Workspace().ID()})
	if store.NoRows(err) {
		return Approval{}, false, nil
	}
	if err != nil {
		return Approval{}, false, err
	}
	a, err := approvalOf(r, now)
	return a, err == nil, err
}

// GetApproval is get_tool_call_approval.
func (s *Surface) GetApproval(ctx context.Context, id string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer release()
	a, ok, err := s.approval(ctx, sess, id, s.d.Now().UTC())
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, notFound("Approval not found")
	}
	hint, err := s.hint(ctx, c.Workspace, a)
	if err != nil {
		return nil, err
	}
	return s.approvalJSON(c, a, hint)
}

// DecideApproval is decide_tool_call_approval; audit is governance's writer.
func (s *Surface) DecideApproval(ctx context.Context, audit governanceapi.AuditWriter, id string, approved bool, comment *string) (wirejson.Object, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	now := s.d.Now().UTC()
	var decided Approval
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		a, ok, err := s.approval(ctx, sess, id, now)
		if err != nil {
			return err
		}
		if !ok {
			return notFound("Approval not found")
		}
		notPending := httpx.HTTPError(http.StatusConflict, "This approval was already decided or has expired")
		if a.Status != "pending" {
			return notPending
		}
		if !callerCanApprove(c, a.Approvers) {
			return httpx.HTTPError(http.StatusForbidden, "You are not an approver of this tool call")
		}
		status, expires := "rejected", store.Timestamptz(time.Time{})
		if approved {
			status, expires = "approved", store.Timestamptz(now.Add(approvedTTL))
		}
		u, _ := uuid.Parse(a.ID)
		r, err := store.New(sess.Q()).SurfaceDecideApproval(ctx, store.SurfaceDecideApprovalParams{
			NewStatus: status, DecidedBy: store.Text(&c.UserID), Now: store.Timestamptz(now),
			Comment: store.Text(comment), ExpiresAt: expires, UpdatedAt: store.Timestamp(now),
			ID: u, WorkspaceID: c.Workspace.ID(),
		})
		if store.NoRows(err) {
			return notPending
		}
		if err != nil {
			return err
		}
		if decided, err = approvalOf(store.SurfaceApprovalRow(r), now); err != nil {
			return err
		}
		action := "tool_call_approval.rejected"
		if approved {
			action = "tool_call_approval.approved"
		}
		return audit.RecordOnce(ctx, sess, governanceapi.AuditRecord{
			EventID: uuid.NewString(), Action: action, ResourceType: "tool_call_approval", ResourceID: decided.ID,
			ActorType: "user", ActorID: c.UserID,
			Metadata: map[string]any{
				"tool": decided.Tool, "connector": decided.Connector, "mcp_instance_id": ptrAny(decided.MCPInstanceID),
				"requested_by": decided.RequestedBy, "client_id": ptrAny(decided.ClientID), "comment": ptrAny(decided.Comment),
			},
		})
	})
	if err != nil {
		return nil, err
	}
	hint, err := s.hint(ctx, c.Workspace, decided)
	if err != nil {
		return nil, err
	}
	return s.approvalJSON(c, decided, hint)
}

func ptrAny(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}
