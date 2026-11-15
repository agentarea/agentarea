package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

// PlatformInbox is api.PlatformInbox over the surface.
type PlatformInbox struct{ s *Surface }

var _ api.PlatformInbox = PlatformInbox{}

// PlatformInbox is the inbox toolset's provider.
func (s *Surface) PlatformInbox() PlatformInbox { return PlatformInbox{s: s} }

func (p PlatformInbox) List(ctx context.Context, c authn.Caller, status *string, agentID string, page, pageSize int) (api.InboxPage, error) {
	statuses := InboxStatuses()
	if status != nil {
		statuses = []string{*status}
	}
	var agent uuid.NullUUID
	if agentID != "" {
		u, err := uuid.Parse(agentID)
		if err != nil {
			return api.InboxPage{}, errors.New("agent_id must be a UUID")
		}
		agent = uuid.NullUUID{UUID: u, Valid: true}
	}
	limit := max(pageSize, 0)
	offset := max(page-1, 0) * limit
	sess, release, err := p.s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return api.InboxPage{}, err
	}
	defer release()
	q := store.New(sess.Q())
	rows, err := q.SurfaceInboxPage(ctx, store.SurfaceInboxPageParams{
		WorkspaceID: c.Workspace.ID(), Statuses: statuses, AgentID: agent, Skip: int32(offset), MaxRows: int32(limit), //nolint:gosec // bounded by the tool
	})
	if err != nil {
		return api.InboxPage{}, err
	}
	total, err := q.SurfaceInboxCount(ctx, store.SurfaceInboxCountParams{WorkspaceID: c.Workspace.ID(), Statuses: statuses, AgentID: agent})
	if err != nil {
		return api.InboxPage{}, err
	}
	out := api.InboxPage{Items: make([]api.InboxItem, 0, len(rows)), Total: total, Page: page, PageSize: pageSize, ToolCallApprovals: []api.HeldToolCall{}}
	for _, r := range rows {
		t, err := taskOf(store.SurfaceTaskRow(r))
		if err != nil {
			return api.InboxPage{}, err
		}
		item := api.InboxItem{ID: t.ID, AgentID: agentOf(t), Description: t.Description, Status: t.Status}
		if !t.CreatedAt.IsZero() {
			at := PyISO(t.CreatedAt, false)
			item.CreatedAt = &at
		}
		out.Items = append(out.Items, item)
	}
	if status != nil && *status != "waiting_for_approval" {
		return out, nil
	}
	now := p.s.d.Now().UTC()
	pending := "pending"
	held, err := q.SurfaceApprovalPage(ctx, store.SurfaceApprovalPageParams{
		WorkspaceID: c.Workspace.ID(), Status: store.Text(&pending), Now: store.Timestamptz(now), MaxRows: int32(limit), //nolint:gosec // bounded by the tool
	})
	if err != nil {
		return api.InboxPage{}, err
	}
	for _, r := range held {
		a, err := approvalOf(store.SurfaceApprovalRow(r), now)
		if err != nil {
			return api.InboxPage{}, err
		}
		url, err := p.s.approvalPageURL(c.Workspace.Slug(), a.ID)
		if err != nil {
			return api.InboxPage{}, err
		}
		out.ToolCallApprovals = append(out.ToolCallApprovals, api.HeldToolCall{
			ID: a.ID, Connector: a.Connector, Tool: a.Tool, RequestedBy: a.RequestedBy, ClientName: a.ClientName,
			URL: url, CreatedAt: PyISO(a.CreatedAt, false), ExpiresAt: PyISO(a.ExpiresAt, false),
		})
	}
	return out, nil
}
