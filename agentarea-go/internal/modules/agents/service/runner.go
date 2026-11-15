package service

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// RunnerClients implements api.RunnerClients (harness_runner.py's reads of
// clients, agents and skills).
type RunnerClients struct{ K *Skills }

var _ api.RunnerClients = RunnerClients{}

// Client is the workspace's client.
func (r RunnerClients) Client(ctx context.Context, ws scope.Workspace, clientID string) (api.RunnerClient, bool, error) {
	id, err := uuid.Parse(clientID)
	if err != nil {
		return api.RunnerClient{}, false, nil
	}
	var out api.RunnerClient
	var found bool
	err = r.K.s.read(ctx, ws, func(sess db.Session) error {
		row, ok, err := clientStore().Get(ctx, sess, id)
		if err != nil || !ok {
			return err
		}
		domains := []string{}
		if len(row.AllowDomains) > 0 {
			if err := json.Unmarshal(row.AllowDomains, &domains); err != nil {
				return fmt.Errorf("client %s allow_domains: %w", id, err)
			}
		}
		out = api.RunnerClient{
			ID: row.ID.String(), WorkspaceID: row.WorkspaceID, Kind: row.Kind, Runner: domain.RunnerKind(row.Kind),
			DefaultModel: str(row.DefaultModel), AllowDomains: domains, Sandbox: row.Sandbox,
		}
		found = true
		return nil
	})
	return out, found, err
}

// RecordHello is RunnerConnection._on_hello's write.
func (r RunnerClients) RecordHello(ctx context.Context, ws scope.Workspace, clientID string, models []api.RunnerModel, defaultModel string) error {
	id, err := uuid.Parse(clientID)
	if err != nil {
		return fmt.Errorf("client %s not found", clientID)
	}
	var raw []byte
	if models != nil {
		for i := range models {
			if models[i].ReasoningLevels == nil {
				models[i].ReasoningLevels = []string{}
			}
		}
		if raw, err = json.Marshal(models); err != nil {
			return err
		}
	}
	var dm *string
	if defaultModel != "" {
		dm = &defaultModel
	}
	return r.K.s.write(ctx, ws, func(sess db.Session) error {
		ok, err := clientStore().RecordRunnerHello(ctx, sess, id, models != nil, raw, dm, r.K.s.d.Now())
		if err == nil && !ok {
			err = fmt.Errorf("client %s not found", clientID)
		}
		return err
	})
}

// Agent is the agent's reasoning level and its instructions with each
// skill's SKILL.md (harness_runner.py _instructions).
func (r RunnerClients) Agent(ctx context.Context, ws scope.Workspace, agentID string) (api.RunnerAgent, error) {
	id, err := uuid.Parse(agentID)
	if err != nil {
		return api.RunnerAgent{}, api.ErrNotFound
	}
	a, ok, err := r.K.s.load(ctx, ws, id, true)
	if err != nil {
		return api.RunnerAgent{}, err
	}
	if !ok {
		return api.RunnerAgent{}, api.ErrNotFound
	}
	var parts []string
	if a.Instruction != nil && strings.TrimSpace(*a.Instruction) != "" {
		parts = append(parts, strings.TrimSpace(*a.Instruction))
	}
	err = r.K.s.read(ctx, ws, func(sess db.Session) error {
		for _, ref := range a.Skills {
			sid, err := uuid.Parse(ref.ID)
			if err != nil {
				return err
			}
			sk, found, err := r.K.get(ctx, sess, sid)
			if err != nil {
				return err
			}
			if !found {
				continue
			}
			md, err := r.K.readSkillMD(ctx, sess, "", &sk, false)
			if err != nil {
				return err
			}
			parts = append(parts, "## Skill: "+ref.Name+"\n\n"+strings.TrimSpace(md))
		}
		return nil
	})
	if err != nil {
		return api.RunnerAgent{}, err
	}
	return api.RunnerAgent{ReasoningEffort: str(a.ReasoningEffort), Instructions: strings.Join(parts, "\n\n")}, nil
}
