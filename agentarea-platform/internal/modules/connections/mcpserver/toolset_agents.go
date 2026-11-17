package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
)

// notFound renders a provider's ErrNotFound as the toolset's own message.
func notFound(err error, msg string) error {
	if errors.Is(err, agentsapi.ErrNotFound) {
		return &toolError{msg}
	}
	return err
}

type agentIDArgs struct {
	AgentID string `json:"agent_id"`
}

// agentsTools is tools/agents_toolset.py.
func agentsTools(a agentsapi.Agents) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List agents", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Limit  *int `json:"limit"`
				Offset int  `json:"offset"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 50
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxListed))
			agents, err := a.List(ctx, c, limit, in.Offset)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(agents))
			for i, s := range agents {
				out[i] = map[string]any{"id": s.ID, "name": s.Name, "description": s.Description}
			}
			return out, nil
		}},
		"get": {title: "Get agent", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[agentIDArgs](args)
			if err != nil {
				return nil, err
			}
			d, err := a.Get(ctx, c, in.AgentID)
			if err != nil {
				return nil, notFound(err, "Agent not found")
			}
			return map[string]any{
				"id": d.ID, "name": d.Name, "description": d.Description, "model_id": d.ModelID,
				"instruction": d.Instruction, "agent_type": d.AgentType,
				"reasoning_effort": d.ReasoningEffort, "reasoning_max_tokens": d.ReasoningMaxTokens,
			}, nil
		}},
		"create": {title: "Create agent", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			doc, err := patchArgs(args, nil, []string{"reasoning_effort", "reasoning_max_tokens", "client_id"})
			if err != nil {
				return nil, err
			}
			ref, err := a.Create(ctx, c, doc)
			if err != nil {
				return nil, err
			}
			return map[string]any{"id": ref.ID, "name": ref.Name}, nil
		}},
		"update": {title: "Update agent", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[agentIDArgs](args)
			if err != nil {
				return nil, err
			}
			doc, err := patchArgs(args, []string{"agent_id"}, []string{"name", "description", "instruction", "model_id", "tools", "reasoning_effort"})
			if err != nil {
				return nil, err
			}
			ref, err := a.Update(ctx, c, in.AgentID, doc)
			if err != nil {
				return nil, notFound(err, "Agent not found")
			}
			return map[string]any{"id": ref.ID, "name": ref.Name}, nil
		}},
		"archive": {title: "Archive agent", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[agentIDArgs](args)
			if err != nil {
				return nil, err
			}
			return existed(a.Archive(ctx, c, in.AgentID), "archived")
		}},
		"restore": {title: "Restore agent", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[agentIDArgs](args)
			if err != nil {
				return nil, err
			}
			return existed(a.Restore(ctx, c, in.AgentID), "restored")
		}},
	}
}

// existed is {key: true}, or {key: false} when there was no such agent.
func existed(err error, key string) (any, error) {
	if errors.Is(err, agentsapi.ErrNotFound) {
		return map[string]any{key: false}, nil
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{key: true}, nil
}
