package service

import (
	"context"
	"fmt"
	"path"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

var _ api.Tasks = (*Surface)(nil)

// continuedSession is continued_session: the session key and trigger id a
// follow-up joins, or empty strings when it starts its own task.
func continuedSession(params map[string]any) (key, triggerID string) {
	session, ok := params["session"].(map[string]any)
	if !ok || session["continue"] != true {
		return "", ""
	}
	key, _ = session["key"].(string)
	trigger := params["trigger_id"]
	if key == "" || trigger == nil || trigger == "" {
		return "", ""
	}
	return key, fmt.Sprint(trigger)
}

// selectionKey is _task_resource_selection_key: the capability identities a
// run is frozen with; ok false when one is malformed.
func selectionKey(params map[string]any) (string, bool) {
	var groups []string
	for _, kind := range []string{"mcps", "skills", "files"} {
		value := params[kind]
		if kind == "mcps" && value == nil {
			if value = params["mcp"]; value == nil {
				value = params["mcp_servers"]
			}
		}
		if value == nil {
			value = []any{}
		}
		list, ok := value.([]any)
		if !ok {
			return "", false
		}
		ids := map[string]bool{}
		for _, item := range list {
			if kind == "files" {
				p, ok := item.(string)
				if !ok {
					return "", false
				}
				p = path.Clean(strings.TrimPrefix(p, "/"))
				if p == "." || strings.HasPrefix(p, "../") || p == ".." {
					return "", false
				}
				ids[p] = true
				continue
			}
			ref := item
			if m, isMap := item.(map[string]any); isMap {
				ref = nil
				for _, k := range []string{"id", "instance_id", "skill_id"} {
					if v, ok := m[k]; ok && v != nil && v != "" {
						ref = v
						break
					}
				}
			}
			s, ok := ref.(string)
			if !ok {
				return "", false
			}
			u, err := uuid.Parse(s)
			if err != nil {
				return "", false
			}
			ids[u.String()] = true
		}
		keys := make([]string, 0, len(ids))
		for k := range ids {
			keys = append(keys, k)
		}
		slices.Sort(keys)
		groups = append(groups, strings.Join(keys, ","))
	}
	return strings.Join(groups, "|"), true
}

// route is _try_route_to_active_workflow: the request queued into the newest
// live task of its session that runs with the same capabilities for the same user.
func (s *Surface) route(ctx context.Context, ws scope.Workspace, req api.TaskRequest, key, triggerID string) (api.TaskSubmitted, bool, error) {
	followUp, isText := req.Parameters["follow_up_message"].(string)
	if !isText && truthy(req.Parameters["trigger_event_file"]) {
		return api.TaskSubmitted{}, false, nil
	}
	message := req.Description
	if isText {
		message = followUp
	}
	incoming, ok := selectionKey(req.Parameters)
	if !ok {
		return api.TaskSubmitted{}, false, nil
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return api.TaskSubmitted{}, false, err
	}
	candidates, err := store.ActiveInSession(ctx, sess, req.AgentID, triggerID, key)
	release()
	if err != nil {
		return api.TaskSubmitted{}, false, err
	}
	for _, cand := range candidates {
		if k, ok := selectionKey(cand.Parameters); !ok || k != incoming || cand.CreatedBy != req.UserID || cand.CreatedBy == "" {
			continue
		}
		routed := api.TaskSubmitted{TaskID: cand.ID, Status: "routed", ExecutionID: cand.ExecutionID, Routed: true}
		if req.Claim != nil {
			claimed, err := req.Claim.Claim(ctx, cand.ID)
			if err != nil {
				return api.TaskSubmitted{}, false, err
			}
			if !claimed {
				s.d.Log.InfoContext(ctx, "Follow-up into task was already queued for this delivery", "task_id", cand.ID)
				return routed, true, nil
			}
		}
		if s.command(ctx, cand.ExecutionID, api.CommandQueueMessage, map[string]any{"message": message}) {
			s.d.Log.InfoContext(ctx, "Routed follow-up to workflow", "execution_id", cand.ExecutionID, "agent_id", req.AgentID)
			return routed, true, nil
		}
		if req.Claim != nil {
			if err := req.Claim.Release(ctx); err != nil {
				return api.TaskSubmitted{}, false, err
			}
		}
	}
	return api.TaskSubmitted{}, false, nil
}

// Submit is route_or_submit_task for another module's run.
func (s *Surface) Submit(ctx context.Context, ws scope.Workspace, req api.TaskRequest) (api.TaskSubmitted, error) {
	if !s.CreateMounted() {
		return api.TaskSubmitted{}, fmt.Errorf("submitting a run needs the policy, launcher and permission ports")
	}
	params := map[string]any{}
	for k, v := range req.Parameters {
		params[k] = v
	}
	req.Parameters = params
	if key, trigger := continuedSession(params); key != "" && req.ScheduledAt == nil {
		routed, ok, err := s.route(ctx, ws, req, key, trigger)
		if err != nil || ok {
			return routed, err
		}
	}
	id := req.TaskID
	if id == "" {
		id = uuid.NewString()
	}
	err := s.start(ctx, ws, runSpec{
		TaskID: id, AgentID: req.AgentID, Description: req.Description, Parameters: params, UserID: req.UserID,
		RequiresHumanApproval: req.RequiresHumanApproval, Metadata: req.Metadata, Provenance: req.Provenance, ScheduledAt: req.ScheduledAt,
	})
	if err != nil {
		return api.TaskSubmitted{}, err
	}
	t, ok, err := s.loadTask(ctx, ws, id)
	if err != nil {
		return api.TaskSubmitted{}, err
	}
	if !ok {
		return api.TaskSubmitted{}, fmt.Errorf("task %s vanished after creation", id)
	}
	out := api.TaskSubmitted{TaskID: t.ID, Status: t.Status}
	if t.ExecutionID != nil {
		out.ExecutionID = *t.ExecutionID
	}
	return out, nil
}
