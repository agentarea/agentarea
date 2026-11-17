package mcpserver

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// maxRunsListed is MAX_RUNS_LISTED: GET /v1/tasks takes at most this many.
const maxRunsListed = 1000

// Bounds of the HTTP routes the toolsets mirror; a toolset clamps to them.
const (
	maxListed       = 1000
	maxPageSize     = 100
	maxListedFiles  = 10_000
	minURLExpiresIn = 60
	maxURLExpiresIn = 86400
)

type runIDArgs struct {
	RunID string `json:"run_id"`
}

// runCall decodes the run id and hands it to f.
func runCall(f func(ctx context.Context, c authn.Caller, runID string) (any, error)) func(context.Context, authn.Caller, json.RawMessage) (any, error) {
	return func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
		in, err := decodeArgs[runIDArgs](args)
		if err != nil {
			return nil, err
		}
		return f(ctx, c, in.RunID)
	}
}

// runsTools is tools/runs_toolset.py.
func runsTools(r runsapi.PlatformRuns) map[string]toolDef {
	return map[string]toolDef{
		"start": {title: "Start run", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				AgentID               string         `json:"agent_id"`
				Description           string         `json:"description"`
				Parameters            map[string]any `json:"parameters"`
				RequiresHumanApproval bool           `json:"requires_human_approval"`
				ProjectID             *string        `json:"project_id"`
				ScheduledAt           *string        `json:"scheduled_at"`
			}](args)
			if err != nil {
				return nil, err
			}
			return r.Start(ctx, c, runsapi.RunStart{
				AgentID: in.AgentID, Description: in.Description, Parameters: in.Parameters,
				RequiresHumanApproval: in.RequiresHumanApproval, ProjectID: in.ProjectID, ScheduledAt: in.ScheduledAt,
			})
		}},
		"list": {title: "List runs", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				AgentID string `json:"agent_id"`
				Limit   *int   `json:"limit"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 20
			if in.Limit != nil {
				limit = *in.Limit
			}
			if limit < 1 || limit > maxRunsListed {
				return nil, &toolError{fmt.Sprintf("limit must be between 1 and %d, got %d", maxRunsListed, limit)}
			}
			return r.List(ctx, c, in.AgentID, limit)
		}},
		"get": {title: "Get run", effect: effectRead, call: runCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			return r.Get(ctx, c, id)
		})},
		"cancel": {title: "Cancel run", effect: effectDestructive, idempotent: true, call: runCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			ok, err := r.Cancel(ctx, c, id)
			if err != nil {
				return nil, err
			}
			return map[string]any{"cancelled": ok}, nil
		})},
		"retry": {title: "Retry failed run", effect: effectWrite, call: runCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			if err := r.Retry(ctx, c, id); err != nil {
				return nil, err
			}
			return map[string]any{"retried": true, "run_id": id}, nil
		})},
		"pause": {title: "Pause run", effect: effectWrite, idempotent: true, call: runCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			ok, err := r.Pause(ctx, c, id)
			if err != nil {
				return nil, err
			}
			return map[string]any{"paused": ok}, nil
		})},
		"resume": {title: "Resume run", effect: effectWrite, idempotent: true, call: runCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			ok, err := r.Resume(ctx, c, id)
			if err != nil {
				return nil, err
			}
			return map[string]any{"resumed": ok}, nil
		})},
		"send_input": {title: "Answer run input request", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				RunID          string         `json:"run_id"`
				InputRequestID string         `json:"input_request_id"`
				Answers        map[string]any `json:"answers"`
			}](args)
			if err != nil {
				return nil, err
			}
			ok, err := r.SendInput(ctx, c, in.RunID, in.InputRequestID, in.Answers)
			if err != nil {
				return nil, err
			}
			return map[string]any{"delivered": ok, "input_request_id": in.InputRequestID}, nil
		}},
		"send_command": {title: "Send run command", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				RunID           string  `json:"run_id"`
				Command         string  `json:"command"`
				Message         *string `json:"message"`
				MessageID       *string `json:"message_id"`
				ModelInstanceID *string `json:"model_instance_id"`
				BudgetUSD       *string `json:"budget_usd"`
			}](args)
			if err != nil {
				return nil, err
			}
			ok, err := r.SendCommand(ctx, c, in.RunID, runsapi.RunCommand{
				Command: in.Command, Message: in.Message, MessageID: in.MessageID,
				ModelInstanceID: in.ModelInstanceID, BudgetUSD: in.BudgetUSD,
			})
			if err != nil {
				return nil, err
			}
			return map[string]any{"delivered": ok, "command": in.Command}, nil
		}},
		"resolve_escalation": {title: "Resolve run escalation", effect: effectPrivileged, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				RunID        string `json:"run_id"`
				EscalationID string `json:"escalation_id"`
				Approved     bool   `json:"approved"`
				Comment      string `json:"comment"`
			}](args)
			if err != nil {
				return nil, err
			}
			ok, err := r.ResolveEscalation(ctx, c, in.RunID, in.EscalationID, in.Approved, in.Comment)
			if err != nil {
				return nil, err
			}
			return map[string]any{"resolved": ok, "approved": in.Approved}, nil
		}},
		"list_pending_escalations": {title: "List pending escalations", effect: effectRead, call: runCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			return r.ListPendingEscalations(ctx, c, id)
		})},
		"continue_run": {title: "Continue run", effect: effectPrivileged, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				RunID               string  `json:"run_id"`
				AdditionalIters     int64   `json:"additional_iterations"`
				AdditionalBudgetUSD *string `json:"additional_budget_usd"`
				AdditionalTokens    int64   `json:"additional_tokens"`
				AdditionalToolCalls int64   `json:"additional_tool_calls"`
			}](args)
			if err != nil {
				return nil, err
			}
			return r.ContinueRun(ctx, c, in.RunID, runsapi.RunGrant{
				Iterations: in.AdditionalIters, Tokens: in.AdditionalTokens, ToolCalls: in.AdditionalToolCalls, BudgetUSD: in.AdditionalBudgetUSD,
			})
		}},
		"get_events": {title: "Get run events", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				RunID     string  `json:"run_id"`
				Limit     *int    `json:"limit"`
				Offset    int     `json:"offset"`
				EventType *string `json:"event_type"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 50
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxPageSize))
			return r.Events(ctx, c, in.RunID, limit, in.Offset, in.EventType)
		}},
	}
}
