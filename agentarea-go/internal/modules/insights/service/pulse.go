package service

import (
	"context"
	"math"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// PulseReads are the owners' tenant counts the pulse is composed of; each reads only its own tables.
type PulseReads struct {
	Identity    identityapi.TenantCounter
	Runs        runsapi.TenantCounter
	Agents      agentsapi.TenantCounter
	Connections connectionsapi.TenantCounter
	Catalog     catalogapi.TenantCounter
	Models      modelsapi.TenantCounter
	Streams     streamsapi.TenantCounter
	Governance  governanceapi.TenantCounter
}

// labeled regroups counts by EnumLabel of their keys (_grouped with label).
func labeled(in map[string]int) map[string]int {
	out := make(map[string]int, len(in))
	for k, n := range in {
		out[analytics.EnumLabel(k)] += n
	}
	return out
}

func slug(slugs map[string]string, id string) string {
	if s, ok := slugs[id]; ok && id != "" {
		return s
	}
	return "custom"
}

// CollectPulse is collect_pulse: every aggregate of the pulse but the installation's own, as of now.
func CollectPulse(ctx context.Context, r PulseReads, now time.Time) (map[string]any, error) {
	day, week, month := now.Add(-24*time.Hour), now.Add(-7*24*time.Hour), now.Add(-30*24*time.Hour)
	ids, err := r.Identity.TenantCounts(ctx, week)
	if err != nil {
		return nil, err
	}
	personal := make([]string, 0, len(ids.NewPersonal))
	for _, w := range ids.NewPersonal {
		personal = append(personal, w.ID)
	}
	runs, err := r.Runs.TenantCounts(ctx, runsapi.Windows{Day: day, Week: week, Month: month}, personal)
	if err != nil {
		return nil, err
	}
	agents, err := r.Agents.TenantCounts(ctx, day, personal)
	if err != nil {
		return nil, err
	}
	conns, err := r.Connections.TenantCounts(ctx)
	if err != nil {
		return nil, err
	}
	providers, err := r.Models.TenantCounts(ctx)
	if err != nil {
		return nil, err
	}
	triggers, err := r.Streams.TenantCounts(ctx)
	if err != nil {
		return nil, err
	}
	policies, err := r.Governance.TenantCounts(ctx)
	if err != nil {
		return nil, err
	}
	var specIDs, itemIDs, providerIDs []string
	for _, c := range conns.MCPBySpec {
		specIDs = append(specIDs, c.Source)
	}
	for _, c := range conns.OpenAPIByItem {
		itemIDs = append(itemIDs, c.Source)
	}
	for id := range agents.SkillsByItem {
		itemIDs = append(itemIDs, id)
	}
	for id := range providers {
		providerIDs = append(providerIDs, id)
	}
	cat, err := r.Catalog.TenantCounts(ctx, specIDs, itemIDs, providerIDs)
	if err != nil {
		return nil, err
	}

	byCatalog, byAuth := map[string]int{}, map[string]int{}
	for _, c := range conns.MCPBySpec {
		byCatalog[slug(cat.SpecSlugs, c.Source)] += c.Count
		byAuth[analytics.EnumLabel(c.AuthType)] += c.Count
	}
	for _, c := range conns.OpenAPIByItem {
		byCatalog[slug(cat.ItemSlugs, c.Source)] += c.Count
		byAuth[analytics.EnumLabel(c.AuthType)] += c.Count
	}
	skills := map[string]int{}
	for id, n := range agents.SkillsByItem {
		skills[slug(cat.ItemSlugs, id)] += n
	}
	llm := map[string]int{}
	for id, n := range providers {
		if t, ok := cat.ProviderTypes[id]; ok {
			llm[analytics.EnumLabel(t)] += n
		}
	}
	var median any
	if runs.MedianDurationSeconds != nil {
		median = math.Round(*runs.MedianDurationSeconds*10) / 10
	}
	bundles := map[string]int{}
	for _, b := range cat.Bundles {
		name := "custom"
		if b.Catalog {
			name = b.Name
		}
		bundles[name] += b.Count
	}
	sizes := map[string]int{"1": 0, "2-5": 0, "6+": 0}
	for members, n := range ids.WorkspacesByMembers {
		switch {
		case members <= 1:
			sizes["1"] += n
		case members <= 5:
			sizes["2-5"] += n
		default:
			sizes["6+"] += n
		}
	}
	within1d, within7d := 0, 0
	for _, w := range ids.NewPersonal {
		first, ok := runs.FirstCompleted[w.ID]
		if !ok {
			continue
		}
		if !first.After(w.CreatedAt.Add(24 * time.Hour)) {
			within1d++
		}
		if !first.After(w.CreatedAt.Add(7 * 24 * time.Hour)) {
			within7d++
		}
	}
	return map[string]any{
		"workspaces": map[string]any{"total": ids.Workspaces, "active_7d": runs.ActiveWorkspaces7d, "active_30d": runs.ActiveWorkspaces30d},
		"users":      map[string]any{"total": ids.Users, "active_7d": runs.ActiveUsers7d, "active_30d": runs.ActiveUsers30d},
		"agents":     map[string]any{"total": agents.Agents, "created_24h": agents.AgentsCreated24h},
		"runs_24h": map[string]any{
			"by_status": labeled(runs.ByStatus), "by_origin": labeled(runs.ByOrigin),
			"failed_by_reason": labeled(runs.FailedByReason), "median_duration_seconds": median,
		},
		"connectors": map[string]any{
			"by_kind":                map[string]any{"mcp": conns.MCP, "openapi": conns.OpenAPI},
			"by_catalog":             byCatalog,
			"by_auth_type":           byAuth,
			"by_verification_status": labeled(conns.MCPByVerification),
		},
		"triggers_active": labeled(triggers),
		"skills":          skills,
		"bundles":         bundles,
		"policies":        policies,
		"clients":         labeled(agents.ClientsByKind),
		"llm_providers":   llm,
		"workspace_sizes": sizes,
		"activation_7d": map[string]any{
			"personal_workspaces": len(ids.NewPersonal), "with_agent": agents.WithAgent,
			"succeeded_within_1d": within1d, "succeeded_within_7d": within7d,
		},
	}, nil
}
