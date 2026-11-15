package service

import (
	"encoding/json"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

func sortBy[T any](s []T, cmp func(a, b T) int) { slices.SortStableFunc(s, cmp) }

// Node types and edge relations of the network graph.
const (
	NodeAgent       = "agent"
	NodeMCPInstance = "mcp_instance"
	NodeOpenAPI     = "openapi_connection"
	NodeSkill       = "skill"
	NodeTrigger     = "trigger"

	RelHasSkill    = "has_skill"
	RelDelegatesTo = "delegates_to"
	RelUsesOpenAPI = "uses_openapi"
	RelUsesMCP     = "uses_mcp"
	RelMemberOf    = "member_of"
	RelHasTrigger  = "has_trigger"

	ScopeEgress = "egress"
)

// Node is one entity of the graph. Metadata holds no null value.
type Node struct {
	ID       string
	Type     string
	Label    string
	Status   *string
	Metadata wirejson.Object
}

// Edge is "{source}-{target}-{relation}".
type Edge struct {
	ID, Source, Target, Relation string
}

// Overlay is a governance interceptor the enterprise graph overlays.
type Overlay struct {
	Name     string
	Category string
	Phases   []string
}

// GovernanceOverlays is the enterprise overlay (_GOVERNANCE_INTERCEPTORS).
func GovernanceOverlays() []Overlay {
	return []Overlay{
		{"cost_budget_guard", "gate", []string{"pre_llm_call"}},
		{"token_budget_guard", "gate", []string{"pre_llm_call"}},
		{"escalation_guard", "gate", []string{"pre_tool_call"}},
		{"prompt_injection_detector", "filter", []string{"pre_llm_call", "post_llm_call"}},
		{"content_policy_enforcer", "filter", []string{"pre_llm_call", "post_llm_call"}},
		{"metrics_observer", "observer", []string{"pre_llm_call", "post_llm_call", "pre_tool_call", "post_tool_call"}},
	}
}

// Topology is GET /network/topology.
type Topology struct {
	Nodes          []Node
	Edges          []Edge
	Governance     []Overlay
	DeploymentMode string
}

// GraphAgent, GraphSkill, GraphInstance, GraphOpenAPI and GraphTrigger are
// what the graph is drawn from.
type GraphAgent struct {
	ID, Name, Status     string
	Description, ModelID *string
	Tools                json.RawMessage
	Skills               []GraphRef
}

// GraphRef is an id and a name.
type GraphRef struct{ ID, Name string }

// GraphSkill is a skill of the workspace.
type GraphSkill struct {
	ID, Name, SourceType, NetworkScope string
	Description                        *string
}

// GraphMember is a bundle membership.
type GraphMember struct{ ParentID, ChildID string }

// GraphInstance is an MCP server instance; SpecJSON is its server spec's JSON, nil when none was found.
type GraphInstance struct {
	ID, Name, NetworkScope string
	ToolCount              int
	JSONSpec, SpecJSON     map[string]any
}

// GraphOpenAPI is an OpenAPI connection.
type GraphOpenAPI struct {
	ID, Name, Status     string
	Description, BaseURL *string
	ToolCount            int
}

// GraphTrigger is a trigger.
type GraphTrigger struct {
	ID, Name, AgentID, Type string
	Active                  bool
}

// GraphInput is the workspace's entities.
type GraphInput struct {
	Agents     []GraphAgent
	Skills     []GraphSkill
	Members    []GraphMember
	Instances  []GraphInstance
	OpenAPI    []GraphOpenAPI
	Triggers   []GraphTrigger
	Enterprise bool
}

func put(o *wirejson.Object, key string, v any) {
	switch x := v.(type) {
	case nil:
		return
	case *string:
		if x == nil {
			return
		}
		v = *x
	}
	*o = append(*o, wirejson.Member{Key: key, Value: v})
}

// FirstIconSrc is the first icons[].src a server JSON declares.
func FirstIconSrc(spec map[string]any) *string {
	icons, _ := spec["icons"].([]any)
	for _, i := range icons {
		if m, ok := i.(map[string]any); ok {
			if s, ok := m["src"].(string); ok && s != "" {
				return &s
			}
		}
	}
	return nil
}

// EndpointHost is the host of json_spec.endpoint_url, never the URL: its path may carry a token.
func EndpointHost(spec map[string]any) *string {
	raw, _ := spec["endpoint_url"].(string)
	if raw == "" {
		return nil
	}
	u, err := url.Parse(raw)
	if err != nil {
		return nil
	}
	h := strings.ToLower(u.Hostname())
	if h == "" {
		return nil
	}
	return &h
}

func toolList(raw json.RawMessage) []any {
	if len(raw) == 0 {
		return nil
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil
	}
	switch t := v.(type) {
	case []any:
		return t
	case wirejson.Object:
		l, _ := t.Get("tools")
		out, _ := l.([]any)
		return out
	}
	return nil
}

func toolsConfig(raw json.RawMessage) any {
	if len(raw) == 0 {
		return nil
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil
	}
	if o, ok := v.(wirejson.Object); ok && len(o) > 0 {
		return o
	}
	return nil
}

func objStr(o wirejson.Object, key string) (string, bool) {
	v, _ := o.Get(key)
	s, ok := v.(string)
	return s, ok
}

func idText(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case json.Number:
		return x.String()
	case bool:
		if x {
			return "True"
		}
		return ""
	case wirejson.Float:
		return wirejson.FormatFloat(float64(x))
	}
	return ""
}

func edge(source, target, rel string) Edge {
	return Edge{ID: source + "-" + target + "-" + rel, Source: source, Target: target, Relation: rel}
}

// BuildTopology draws the graph (get_network_topology).
func BuildTopology(in GraphInput) Topology {
	t := Topology{Nodes: []Node{}, Edges: []Edge{}, Governance: []Overlay{}, DeploymentMode: "oss"}
	if in.Enterprise {
		t.Governance, t.DeploymentMode = GovernanceOverlays(), "enterprise"
	}
	live := map[string]bool{}
	for _, a := range in.Agents {
		live[a.ID] = true
	}
	openapiByName, openapiIDs := map[string]string{}, map[string]bool{}
	for _, c := range in.OpenAPI {
		openapiByName[c.Name] = c.ID
		openapiIDs[c.ID] = true
	}
	egress := map[string]bool{}
	for _, s := range in.Skills {
		if s.NetworkScope == ScopeEgress {
			egress[s.ID] = true
		}
	}
	for _, a := range in.Agents {
		var md wirejson.Object
		put(&md, "model_id", a.ModelID)
		put(&md, "description", a.Description)
		if len(a.Skills) > 0 {
			skills := make([]any, len(a.Skills))
			embedded := 0
			for i, s := range a.Skills {
				skills[i] = wirejson.Object{{Key: "id", Value: s.ID}, {Key: "name", Value: s.Name}}
				if !egress[s.ID] {
					embedded++
				}
			}
			md = append(md, wirejson.Member{Key: "skills", Value: skills})
			if embedded > 0 {
				md = append(md, wirejson.Member{Key: "embedded_skills_count", Value: embedded})
			}
		}
		put(&md, "tools_config", toolsConfig(a.Tools))
		status := a.Status
		t.Nodes = append(t.Nodes, Node{ID: a.ID, Type: NodeAgent, Label: a.Name, Status: &status, Metadata: md})
		for _, s := range a.Skills {
			if egress[s.ID] {
				t.Edges = append(t.Edges, edge(a.ID, s.ID, RelHasSkill))
			}
		}
		seenMCP, seenOpenAPI, seenDelegates := map[string]bool{}, map[string]bool{}, map[string]bool{}
		for _, raw := range toolList(a.Tools) {
			tool, ok := raw.(wirejson.Object)
			if !ok {
				continue
			}
			typ, _ := objStr(tool, "type")
			sv, _ := tool.Get("settings")
			settings, _ := sv.(wirejson.Object)
			switch typ {
			case "agent":
				bound, _ := objStr(settings, "agent_id")
				if bound != "" && live[bound] && bound != a.ID && !seenDelegates[bound] {
					seenDelegates[bound] = true
					t.Edges = append(t.Edges, edge(a.ID, bound, RelDelegatesTo))
				}
				continue
			case "openapi":
				cv, _ := settings.Get("openapi_connection_id")
				target := ""
				if id := idText(cv); id != "" && openapiIDs[id] {
					target = id
				} else {
					name, _ := objStr(tool, "name")
					target = openapiByName[name]
				}
				if target != "" && !seenOpenAPI[target] {
					seenOpenAPI[target] = true
					t.Edges = append(t.Edges, edge(a.ID, target, RelUsesOpenAPI))
				}
				continue
			}
			var server string
			for _, k := range []string{"tool_server_id", "server_id", "mcp_instance_id"} {
				v, _ := tool.Get(k)
				if server = idText(v); server != "" {
					break
				}
			}
			if server != "" && !seenMCP[server] {
				seenMCP[server] = true
				t.Edges = append(t.Edges, edge(a.ID, server, RelUsesMCP))
			}
		}
	}
	for _, s := range in.Skills {
		if !egress[s.ID] {
			continue
		}
		var md wirejson.Object
		put(&md, "source_type", s.SourceType)
		put(&md, "description", s.Description)
		put(&md, "network_scope", s.NetworkScope)
		t.Nodes = append(t.Nodes, Node{ID: s.ID, Type: NodeSkill, Label: s.Name, Metadata: md})
	}
	for _, m := range in.Members {
		if egress[m.ParentID] && egress[m.ChildID] {
			t.Edges = append(t.Edges, edge(m.ChildID, m.ParentID, RelMemberOf))
		}
	}
	for _, i := range in.Instances {
		md := wirejson.Object{{Key: "tool_count", Value: i.ToolCount}}
		put(&md, "network_scope", i.NetworkScope)
		icon := FirstIconSrc(i.JSONSpec)
		if icon == nil {
			icon = FirstIconSrc(i.SpecJSON)
		}
		put(&md, "icon_url", icon)
		put(&md, "endpoint_host", EndpointHost(i.JSONSpec))
		label := i.Name
		if label == "" {
			label = i.ID
		}
		t.Nodes = append(t.Nodes, Node{ID: i.ID, Type: NodeMCPInstance, Label: label, Metadata: md})
	}
	for _, c := range in.OpenAPI {
		var md wirejson.Object
		put(&md, "base_url", c.BaseURL)
		put(&md, "description", c.Description)
		md = append(md, wirejson.Member{Key: "tool_count", Value: c.ToolCount}, wirejson.Member{Key: "network_scope", Value: ScopeEgress})
		label := c.Name
		if label == "" {
			label = c.ID
		}
		status := c.Status
		t.Nodes = append(t.Nodes, Node{ID: c.ID, Type: NodeOpenAPI, Label: label, Status: &status, Metadata: md})
	}
	for _, tr := range in.Triggers {
		status := "inactive"
		if tr.Active {
			status = "active"
		}
		t.Nodes = append(t.Nodes, Node{ID: tr.ID, Type: NodeTrigger, Label: tr.Name, Status: &status,
			Metadata: wirejson.Object{{Key: "trigger_type", Value: tr.Type}}})
		if tr.AgentID != "" {
			t.Edges = append(t.Edges, edge(tr.AgentID, tr.ID, RelHasTrigger))
		}
	}
	return t
}

// Person is one person of the workspace; Email is set only for the caller.
type Person struct {
	UserID string
	Email  *string
}

// Access is a person's admission to run an agent.
type Access struct {
	UserID, AgentID string
	Allowed         bool
	Reason          string
}

// PeopleAccess is GET /network/people-access.
type PeopleAccess struct {
	WorkspaceID string
	People      []Person
	Access      []Access
	Complete    bool
	TotalPeople int
	TotalAgents int
}

// People and agents evaluated at most (_MAX_PEOPLE, _MAX_AGENTS).
const (
	MaxPeople = 100
	MaxAgents = 100
)

// SelectPeople is the members and the owner, sorted, cut to MaxPeople with
// the owner always kept, and the size of the whole set.
func SelectPeople(members []string, owner string) (selected []string, total int) {
	set := map[string]bool{}
	for _, m := range members {
		set[m] = true
	}
	if owner != "" {
		set[owner] = true
	}
	all := make([]string, 0, len(set))
	for id := range set {
		all = append(all, id)
	}
	slices.Sort(all)
	selected = all[:min(len(all), MaxPeople)]
	if owner != "" && !slices.Contains(selected, owner) {
		selected = append(slices.Clone(selected[:MaxPeople-1]), owner)
		slices.Sort(selected)
	}
	return selected, len(all)
}

// UpcomingItem is one entry of an agent's agenda.
type UpcomingItem struct {
	FiresAt        time.Time
	Kind           string
	Title          string
	TriggerID      *string
	TaskID         *string
	CronExpression *string
}

// DayTasks is one day of an agent's tasks.
type DayTasks struct {
	Date                             string
	Completed, Failed, InputRequired int64
}

// Overview is GET /agents/{id}/overview.
type Overview struct {
	CostToday, CostMTD money.Decimal
	TasksDoneToday     int64
	TasksFailedToday   int64
	LastActivityAt     *time.Time
	DailySpend         []DaySpend
	DailyTasks         []DayTasks
	Upcoming           []UpcomingItem
}
