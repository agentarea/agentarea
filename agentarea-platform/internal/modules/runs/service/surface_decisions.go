package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

const (
	approvalApproved = "approval.approved"
	approvalDenied   = "approval.denied"
)

// DecisionsMounted is whether the audit reader the decisions route needs is wired.
func (s *Surface) DecisionsMounted() bool { return s.d.AuditReader != nil }

// Decisions is list_approval_decisions: answered approval requests from the
// audit trail, newest first.
func (s *Surface) Decisions(ctx context.Context, page, pageSize int) (wirejson.Object, error) {
	const failed = "Failed to list approval decisions"
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, s.internal(ctx, failed, err)
	}
	defer release()
	rows, total, err := s.d.AuditReader.ResourceEvents(ctx, sess, governanceapi.AuditPage{
		ResourceType: "task", Actions: []string{approvalApproved, approvalDenied},
		Limit: pageSize, Offset: (page - 1) * pageSize,
	})
	if err != nil {
		return nil, s.internal(ctx, failed, err)
	}
	taskIDs := make([]uuid.UUID, len(rows))
	metas := make([]wirejson.Object, len(rows))
	agentIDs := []string{}
	seen := map[string]bool{}
	for i, r := range rows {
		if taskIDs[i], err = uuid.Parse(r.ResourceID); err != nil {
			return nil, s.internal(ctx, failed, err)
		}
		if metas[i], err = auditMetadata(r.Metadata); err != nil {
			return nil, s.internal(ctx, failed, err)
		}
		if id := decisionAgentID(metas[i]); id != nil && !seen[*id] {
			seen[*id] = true
			agentIDs = append(agentIDs, *id)
		}
	}
	descRows, err := store.New(sess.Q()).SurfaceTaskDescriptions(ctx, store.SurfaceTaskDescriptionsParams{WorkspaceID: c.Workspace.ID(), Ids: taskIDs})
	if err != nil {
		return nil, s.internal(ctx, failed, err)
	}
	descriptions := make(map[uuid.UUID]string, len(descRows))
	for _, d := range descRows {
		descriptions[d.ID] = d.Description
	}
	names, err := s.names(ctx, c.Workspace, agentIDs)
	if err != nil {
		return nil, s.internal(ctx, failed, err)
	}
	items := make([]any, len(rows))
	for i, r := range rows {
		items[i] = decisionJSON(r, taskIDs[i], metas[i], descriptions, names)
	}
	return wirejson.Object{
		{Key: "items", Value: items}, {Key: "total", Value: total},
		{Key: "page", Value: page}, {Key: "page_size", Value: pageSize},
	}, nil
}

func field(o wirejson.Object, key string) any {
	v, _ := o.Get(key)
	return v
}

func auditMetadata(raw []byte) (wirejson.Object, error) {
	if len(raw) == 0 {
		return wirejson.Object{}, nil
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil, err
	}
	if o, ok := v.(wirejson.Object); ok {
		return o, nil
	}
	return wirejson.Object{}, nil
}

// decisionAgentID is the metadata's agent_id when it is a UUID; anything else
// answers null rather than failing the page.
func decisionAgentID(meta wirejson.Object) *string {
	v, ok := field(meta, "agent_id").(string)
	if !ok {
		return nil
	}
	id, err := uuid.Parse(v)
	if err != nil {
		return nil
	}
	s := id.String()
	return &s
}

func decisionJSON(r governanceapi.AuditEntry, taskID uuid.UUID, meta wirejson.Object, descriptions map[uuid.UUID]string, names map[string]string) wirejson.Object {
	escalation := field(meta, "escalation_id")
	escID := ""
	if truthy(escalation) {
		escID = pyStr(escalation)
	}
	var agentID, agentName any
	if id := decisionAgentID(meta); id != nil {
		agentID, agentName = *id, nameOf(names, *id)
	}
	var description any
	if d, ok := descriptions[taskID]; ok {
		description = d
	}
	var tool any
	if t, ok := field(meta, "tool").(string); ok {
		tool = t
	}
	var decidedBy any
	if r.ActorType == "user" {
		decidedBy = r.ActorID
	}
	var comment any
	if cm, ok := field(meta, "comment").(string); ok && cm != "" {
		comment = cm
	}
	return wirejson.Object{
		{Key: "escalation_id", Value: escID},
		{Key: "task_id", Value: taskID.String()},
		{Key: "agent_id", Value: agentID},
		{Key: "agent_name", Value: agentName},
		{Key: "task_description", Value: description},
		{Key: "tool_name", Value: tool},
		{Key: "approved", Value: r.Action == approvalApproved},
		{Key: "decided_by", Value: decidedBy},
		{Key: "comment", Value: comment},
		{Key: "decided_at", Value: PyISO(r.CreatedAt, true)},
	}
}
