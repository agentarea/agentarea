package service

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// Export is the workspace_config toolset's export: admin check, then ExportYAML.
func (m *Misc) Export(ctx context.Context, c authn.Caller) (string, error) {
	if err := m.s.RequireAdmin(authn.WithCaller(ctx, c)); err != nil {
		return "", err
	}
	return m.ExportYAML(ctx, c)
}

// ExportYAML is WorkspaceExportService.export_workspace after the admin check.
func (m *Misc) ExportYAML(ctx context.Context, c authn.Caller) (string, error) {
	switch {
	case m.d.ExportWorkspaces == nil:
		return "", &UnwiredError{Feature: "exporting the workspace (workspace name, identity)"}
	case m.d.ExportSkills == nil:
		return "", &UnwiredError{Feature: "exporting the workspace (skills)"}
	case m.d.ExportMCPs == nil:
		return "", &UnwiredError{Feature: "exporting the workspace (MCP connections)"}
	case m.d.ExportTriggers == nil:
		return "", &UnwiredError{Feature: "exporting the workspace (triggers)"}
	}
	name, err := m.d.ExportWorkspaces.WorkspaceName(ctx, c)
	if err != nil {
		return "", err
	}
	in := domain.ExportInput{WorkspaceID: c.Workspace.ID(), WorkspaceSlug: c.Workspace.Slug(), WorkspaceName: name}
	if in.Skills, err = m.d.ExportSkills.ExportSkills(ctx, c); err != nil {
		return "", err
	}
	if in.Agents, err = m.exportAgents(ctx, c); err != nil {
		return "", err
	}
	instances, err := m.d.ExportMCPs.ExportInstances(ctx, c)
	if err != nil {
		return "", err
	}
	for _, inst := range instances {
		spec, _ := exportYAMLValue(inst.Spec).(domain.YAMLMap)
		in.MCPs = append(in.MCPs, domain.ExportMCP{ID: inst.ID, Name: inst.Name, Builtin: inst.IsCatalog || inst.ManagedBy == "platform",
			Spec: spec, EnvVars: inst.EnvVars, ContextSigning: inst.ContextSigning})
	}
	triggers, err := m.d.ExportTriggers.ExportTriggers(ctx, c)
	if err != nil {
		return "", err
	}
	for _, t := range triggers {
		text, _ := t.TaskParameters.Get("text")
		in.Triggers = append(in.Triggers, domain.ExportTrigger{ID: t.ID, Name: t.Name, Kind: t.TriggerType, AgentID: t.AgentID,
			HasConditions: toolsTruthy(t.Conditions), Text: exportYAMLValue(text), Cron: t.CronExpression,
			Timezone: t.Timezone, Enabled: t.IsActive})
	}
	bundle, err := domain.ExportBundle(in, func(msg string, args ...any) {
		if m.s.d.Log != nil {
			m.s.d.Log.WarnContext(ctx, fmt.Sprintf(msg, args...))
		}
	})
	if err != nil {
		return "", err
	}
	return domain.SafeDumpYAML(bundle), nil
}

// exportAgents is AgentService.list() then get_with_skills for each.
func (m *Misc) exportAgents(ctx context.Context, c authn.Caller) ([]domain.ExportAgent, error) {
	var out []domain.ExportAgent
	err := m.s.read(ctx, c.Workspace, func(sess db.Session) error {
		all, err := m.s.store.List(ctx, sess)
		if err != nil {
			return err
		}
		for _, a := range all {
			if a.Status == domain.StatusArchived || a.HarnessClientID != nil || a.IsCatalog {
				continue
			}
			skills, err := m.s.store.Skills(ctx, sess, uuid.MustParse(a.ID))
			if err != nil {
				return err
			}
			ea := domain.ExportAgent{ID: a.ID, Name: a.Name, Tools: exportTools(a.Tools)}
			if a.Instruction != nil {
				ea.Instruction = *a.Instruction
			}
			for _, sk := range skills {
				ea.Skills = append(ea.Skills, domain.ExportAgentSkill{ID: sk.ID, Name: sk.Name})
			}
			out = append(out, ea)
		}
		return nil
	})
	return out, err
}

// exportTools reads the stored tools column as the export does: a legacy
// dict's "tools" entry, dict entries only, entries without a name skipped.
func exportTools(raw []byte) []domain.ExportTool {
	if len(raw) == 0 {
		return nil
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil
	}
	if o, ok := v.(wirejson.Object); ok {
		v, _ = o.Get("tools")
	}
	list, _ := v.([]any)
	var out []domain.ExportTool
	for _, item := range list {
		o, ok := item.(wirejson.Object)
		if !ok {
			continue
		}
		name, _ := o.Get("name")
		typ, _ := o.Get("type")
		t := domain.ExportTool{Type: exportYAMLValue(typ)}
		if name != nil {
			t.HasName = true
			t.Name = exportPyStrOf(exportYAMLValue(name))
		}
		out = append(out, t)
	}
	return out
}

func exportPyStrOf(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case domain.YAMLInt:
		return string(x)
	case domain.YAMLFloat:
		return string(x)
	}
	b, _ := wirejson.Marshal(v, wirejson.Compact)
	return string(b)
}

// exportYAMLValue converts decoded JSON (mode="json" values) to YAML values.
func exportYAMLValue(v any) any {
	switch x := v.(type) {
	case wirejson.Object:
		out := make(domain.YAMLMap, len(x))
		for i, m := range x {
			out[i] = domain.YAMLItem{Key: m.Key, Value: exportYAMLValue(m.Value)}
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = exportYAMLValue(e)
		}
		return out
	case wirejson.Float:
		return domain.YAMLFloat(wirejson.FormatFloat(float64(x)))
	case float64:
		return domain.YAMLFloat(wirejson.FormatFloat(x))
	case json.Number:
		if n, ok := new(big.Int).SetString(string(x), 10); ok {
			return domain.YAMLInt(n.String())
		}
		return domain.YAMLInt(string(x))
	}
	return v
}
