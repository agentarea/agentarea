package domain

import (
	"encoding/json"
	"net/url"
	"regexp"
	"strings"
)

// A2AAgentIDPlaceholder is the label of AGENTAREA_A2A_AGENT_URL an agent's id replaces.
const A2AAgentIDPlaceholder = "{agent_id}"

const (
	a2uiExtensionURI   = "https://a2ui.org/a2a-extension/a2ui/v0.9"
	a2uiBasicCatalog   = "https://a2ui.org/specification/v0_9/basic_catalog.json"
	a2aBearerScheme    = "bearer"
	a2aSpecURL         = "https://a2aproject.github.io/A2A/latest/specification/"
	a2aRFC8615URL      = "https://tools.ietf.org/html/rfc8615"
	a2aProtocolVersion = "1.0"
)

func a2aModes() []any { return []any{"text/plain", "application/json"} }

// A2AAPIRPCURL is agent_rpc_url: the agent's JSON-RPC endpoint under the API host.
func A2AAPIRPCURL(apiURL, agentID string) string {
	return strings.TrimRight(apiURL, "/") + "/v1/agents/" + agentID + "/a2a/rpc"
}

// A2AAddress is AppSettings.a2a_agent_url: the agent's own origin.
func A2AAddress(agentURL, agentID string) string {
	return strings.ReplaceAll(strings.TrimRight(agentURL, "/"), A2AAgentIDPlaceholder, agentID)
}

// A2AHostRPCURL is agent_host_rpc_url: the root of the agent's own host.
func A2AHostRPCURL(agentURL, agentID string) string { return A2AAddress(agentURL, agentID) + "/" }

var a2aHostUUID = regexp.MustCompile(`^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$`)

// A2AHostAgent is Starlette's Host("{agent_id:uuid}.<rest>") match: the agent
// id the request's Host header names, canonical, when it is an agent host.
func A2AHostAgent(agentURL, hostHeader string) (string, bool) {
	u, err := url.Parse(strings.Replace(agentURL, A2AAgentIDPlaceholder, "x", 1))
	if err != nil {
		return "", false
	}
	suffix := strings.TrimPrefix(strings.ToLower(u.Hostname()), "x")
	host, _, _ := strings.Cut(hostHeader, ":")
	if suffix == "" || !strings.HasSuffix(host, suffix) {
		return "", false
	}
	label := strings.TrimSuffix(host, suffix)
	if !a2aHostUUID.MatchString(label) {
		return "", false
	}
	hex := strings.ToLower(strings.ReplaceAll(label, "-", ""))
	return hex[:8] + "-" + hex[8:12] + "-" + hex[12:16] + "-" + hex[16:20] + "-" + hex[20:], true
}

// a2aOrigin is urlsplit's "{scheme}://{netloc}".
func a2aOrigin(raw string) string {
	scheme, rest, ok := strings.Cut(raw, ":")
	if !ok {
		return "://"
	}
	netloc := ""
	if strings.HasPrefix(rest, "//") {
		rest = rest[2:]
		if i := strings.IndexAny(rest, "/?#"); i >= 0 {
			rest = rest[:i]
		}
		netloc = rest
	}
	return strings.ToLower(scheme) + "://" + netloc
}

func a2aHasTools(raw []byte) bool {
	var v any
	if json.Unmarshal(raw, &v) != nil {
		return false
	}
	l, ok := v.([]any)
	return ok && len(l) > 0
}

func a2aSkill(id, name, description string, tags, in, out []any) A2AJSON {
	return A2AJSON{
		{Key: "id", Value: id}, {Key: "name", Value: name}, {Key: "description", Value: description},
		{Key: "tags", Value: tags}, {Key: "inputModes", Value: in}, {Key: "outputModes", Value: out},
	}
}

func a2aSkills(a Agent, extended bool) []any {
	text := []any{"text/plain"}
	skills := []any{a2aSkill("text-processing", "Text Processing", "Process and respond to text messages using "+a.Name,
		[]any{"text", "chat"}, text, text)}
	if !extended {
		return skills
	}
	if a2aHasTools(a.Tools) {
		skills = append(skills, a2aSkill("tool-execution", "Tool Execution", "Execute tools and integrations using "+a.Name,
			[]any{"tools", "integration"}, text, a2aModes()))
	}
	if a.Planning != nil && *a.Planning {
		skills = append(skills, a2aSkill("task-planning", "Task Planning", "Break down complex tasks into steps using "+a.Name,
			[]any{"planning"}, text, text))
	}
	return skills
}

// A2ACard is build_agent_card rendered by MessageToDict: the card for a,
// whose endpoint is rpcURL; extended adds the skills only members see.
func A2ACard(a Agent, rpcURL string, extended bool) A2AJSON {
	description := "AI agent " + a.Name
	if a.Description != nil && *a.Description != "" {
		description = *a.Description
	}
	capabilities := A2AJSON{{Key: "streaming", Value: true}, {Key: "pushNotifications", Value: true}}
	if a.A2UIEnabled != nil && *a.A2UIEnabled {
		capabilities = append(capabilities, A2AMember{Key: "extensions", Value: []any{A2AJSON{
			{Key: "uri", Value: a2uiExtensionURI},
			{Key: "params", Value: A2AJSON{{Key: "supportedCatalogIds", Value: []any{a2uiBasicCatalog}}}},
		}}})
	}
	capabilities = append(capabilities, A2AMember{Key: "extendedAgentCard", Value: true})
	card := A2AJSON{}
	if a.Name != "" {
		card = append(card, A2AMember{Key: "name", Value: a.Name})
	}
	interfaceJSON := A2AJSON{}
	if rpcURL != "" {
		interfaceJSON = append(interfaceJSON, A2AMember{Key: "url", Value: rpcURL})
	}
	interfaceJSON = append(interfaceJSON, A2AMember{Key: "protocolBinding", Value: "JSONRPC"}, A2AMember{Key: "protocolVersion", Value: a2aProtocolVersion})
	return append(card,
		A2AMember{Key: "description", Value: description},
		A2AMember{Key: "supportedInterfaces", Value: []any{interfaceJSON}},
		A2AMember{Key: "provider", Value: A2AJSON{{Key: "url", Value: a2aOrigin(rpcURL)}, {Key: "organization", Value: "AgentArea"}}},
		A2AMember{Key: "version", Value: "1.0.0"},
		A2AMember{Key: "capabilities", Value: capabilities},
		A2AMember{Key: "securitySchemes", Value: A2AJSON{{Key: a2aBearerScheme, Value: A2AJSON{
			{Key: "httpAuthSecurityScheme", Value: A2AJSON{{Key: "scheme", Value: "bearer"}}},
		}}}},
		A2AMember{Key: "securityRequirements", Value: []any{A2AJSON{{Key: "schemes", Value: A2AJSON{{Key: a2aBearerScheme, Value: A2AJSON{}}}}}}},
		A2AMember{Key: "defaultInputModes", Value: a2aModes()},
		A2AMember{Key: "defaultOutputModes", Value: a2aModes()},
		A2AMember{Key: "skills", Value: a2aSkills(a, extended)},
	)
}

func a2aDescription(a Agent) any {
	if a.Description == nil {
		return nil
	}
	return *a.Description
}

// A2AInfo is get_agent_a2a_info's document.
func A2AInfo(a Agent, apiURL, agentURL string) A2AJSON {
	base := strings.TrimRight(apiURL, "/")
	methods := []any{
		"SendMessage", "SendStreamingMessage", "GetTask", "CancelTask", "SubscribeToTask", "ListTasks",
		"CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig", "ListTaskPushNotificationConfigs",
		"DeleteTaskPushNotificationConfig", "GetExtendedAgentCard",
	}
	return A2AJSON{
		{Key: "protocol", Value: "A2A"},
		{Key: "version", Value: "1.0.0"},
		{Key: "server", Value: "AgentArea"},
		{Key: "agent", Value: A2AJSON{
			{Key: "id", Value: a.ID}, {Key: "name", Value: a.Name}, {Key: "description", Value: a2aDescription(a)}, {Key: "status", Value: a.Status},
		}},
		{Key: "compliance", Value: A2AJSON{
			{Key: "a2a_specification", Value: a2aSpecURL},
			{Key: "rfc_8615", Value: a2aRFC8615URL},
			{Key: "json_rpc", Value: "https://www.jsonrpc.org/specification/v2"},
		}},
		{Key: "a2a_url", Value: A2AAddress(agentURL, a.ID)},
		{Key: "endpoints", Value: A2AJSON{
			{Key: "agent_card", Value: base + "/v1/agents/" + a.ID + "/.well-known/agent-card.json"},
			{Key: "rpc", Value: A2AAPIRPCURL(apiURL, a.ID)},
		}},
		{Key: "supported_methods", Value: methods},
		{Key: "capabilities", Value: A2AJSON{
			{Key: "streaming", Value: true}, {Key: "pushNotifications", Value: true}, {Key: "extendedAgentCard", Value: true},
		}},
		{Key: "authentication", Value: A2AJSON{
			{Key: "supported", Value: true}, {Key: "methods", Value: []any{"bearer", "api_key"}}, {Key: "required", Value: false},
		}},
	}
}

// A2AWellKnownIndex is get_agent_well_known_index's document.
func A2AWellKnownIndex(a Agent, apiURL, agentURL string) A2AJSON {
	base := strings.TrimRight(apiURL, "/") + "/v1/agents/" + a.ID + "/.well-known/"
	return A2AJSON{
		{Key: "message", Value: "A2A Protocol Well-Known Endpoints for " + a.Name},
		{Key: "agent", Value: A2AJSON{{Key: "id", Value: a.ID}, {Key: "name", Value: a.Name}, {Key: "description", Value: a2aDescription(a)}}},
		{Key: "endpoints", Value: A2AJSON{
			{Key: "agent-card.json", Value: base + "agent-card.json"},
			{Key: "a2a-info.json", Value: base + "a2a-info.json"},
		}},
		{Key: "specification", Value: a2aSpecURL},
		{Key: "rfc", Value: a2aRFC8615URL},
		{Key: "a2a_url", Value: A2AAddress(agentURL, a.ID)},
	}
}

// A2ACardAddress is agent_address: the form of a pasted agent URL a delegate stores.
func A2ACardAddress(raw string) string {
	address := strings.TrimSuffix(a2aPyStrip(raw), "/.well-known/agent-card.json")
	return strings.TrimRight(address, "/")
}
