package main

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
)

// Modules are the packages generated under api/openapi, one per module.
func Modules() []string {
	return []string{
		"agents", "catalog", "connections", "governance", "identity", "insights",
		"models", "projects", "runs", "sandbox", "streams", "wallet",
	}
}

// routerModule maps a FastAPI router file (agentarea-platform/apps/api/agentarea_api/api/v1,
// plus main.py) to its module, following the ownership map of the first wave brief.
func routerModules() map[string]string {
	return map[string]string{
		"workspaces": "identity", "workspace_invitations": "identity", "api_keys": "identity",
		"principals": "identity", "access_control": "identity", "external_identities": "identity",
		"registries": "catalog", "workspace_registries": "catalog", "provider_specs": "catalog",
		"model_specs": "catalog", "mcp_servers_specifications": "catalog", "bundles": "catalog",
		"agents": "agents", "agents_a2a": "agents", "agents_well_known": "agents",
		"a2a_agent_cards": "agents", "skills": "agents", "skill_collections": "agents",
		"clients": "agents", "task_definitions": "agents", "workspace_config": "agents",
		"projects":     "projects",
		"agents_tasks": "runs", "task_event_feed": "runs", "inbox": "runs",
		"tool_call_approvals": "runs", "harness_runner": "runs",
		"provider_configs": "models", "model_instances": "models", "pricing": "models",
		"mcp_server_instances": "connections", "mcp_auth_configs": "connections",
		"mcp_oauth_as": "connections", "mcp_oauth_links": "connections", "mcp_proxy": "connections",
		"client_mcp": "connections", "connection_mcp": "connections", "openapi_connections": "connections",
		"oauth_connect": "connections", "oauth_app_credentials": "connections",
		"sandboxes": "sandbox", "files": "sandbox",
		"streams": "streams", "triggers": "streams", "webhooks": "streams", "stream_event_feed": "streams",
		"policies": "governance", "governance": "governance", "audit": "governance",
		"workspace_secrets": "governance", "egress_exits": "governance",
		"wallet":    "wallet",
		"dashboard": "insights", "network": "insights", "network_people": "insights",
		"analytics": "insights", "agent_overview": "insights",
		// GET /, /health: no module owns them; insights serves platform status.
		"main": "insights",
	}
}

func loadOwners(path string) (map[string]string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var rows []struct {
		OperationID string `json:"operation_id"`
		RouterFile  string `json:"router_file"`
	}
	if err := json.Unmarshal(b, &rows); err != nil {
		return nil, err
	}
	owners := make(map[string]string, len(rows))
	for _, r := range rows {
		m, ok := routerModules()[r.RouterFile]
		if !ok {
			return nil, fmt.Errorf("router file %q has no module", r.RouterFile)
		}
		owners[r.OperationID] = m
	}
	return owners, nil
}

var nonAlnum = regexp.MustCompile(`[^A-Za-z0-9]+`)

// camel mirrors the Go name oapi-codegen derives from an operation id closely
// enough to detect collisions.
func camel(s string) string {
	var sb strings.Builder
	for _, w := range nonAlnum.Split(s, -1) {
		if w != "" {
			sb.WriteString(strings.ToUpper(w[:1]) + w[1:])
		}
	}
	return sb.String()
}

func asMap(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func isNullSchema(v any) bool {
	m := asMap(v)
	return len(m) == 1 && m["type"] == "null"
}

// operations calls fn for every operation in deterministic order.
func operations(doc map[string]any, fn func(path, method string, op map[string]any)) {
	paths := asMap(doc["paths"])
	for _, p := range sortedKeys(paths) {
		item := asMap(paths[p])
		for _, m := range sortedKeys(item) {
			if op := asMap(item[m]); op != nil && op["operationId"] != nil {
				fn(p, m, op)
			}
		}
	}
}

// preprocess applies the spec fixes of decision 13 in place and returns the
// final operation id to module map:
//  1. operation ids made unique after Go camel-casing (_dupN suffix),
//  2. media schemas that are exactly {} become json.RawMessage,
//  3. top-level media anyOf [$ref, null] collapses to the $ref,
//  4. one module tag per operation,
//  5. x-omitempty:false on optional nullable properties (wire parity: FastAPI writes null).
func preprocess(doc map[string]any, owners map[string]string) (map[string]string, error) {
	ops := map[string]string{}
	seen := map[string]int{}
	var missing []string
	operations(doc, func(path, method string, op map[string]any) {
		orig := op["operationId"].(string)
		mod, ok := owners[orig]
		if !ok {
			missing = append(missing, orig)
			return
		}
		id := orig
		seen[camel(orig)]++
		if n := seen[camel(orig)]; n > 1 {
			id = fmt.Sprintf("%s_dup%d", orig, n)
			op["operationId"] = id
		}
		op["tags"] = []any{mod}
		ops[id] = mod
		fixMedia(op)
	})
	if len(missing) > 0 {
		sort.Strings(missing)
		return nil, fmt.Errorf("operations without a router file: %v", missing)
	}
	emitNull(doc)
	return ops, nil
}

func fixMedia(op map[string]any) {
	var contents []map[string]any
	for _, r := range asMap(op["responses"]) {
		contents = append(contents, asMap(asMap(r)["content"]))
	}
	contents = append(contents, asMap(asMap(op["requestBody"])["content"]))
	for _, c := range contents {
		for _, mt := range c {
			mtm := asMap(mt)
			sc := asMap(mtm["schema"])
			if a, ok := sc["anyOf"].([]any); ok && len(a) == 2 && (isNullSchema(a[0]) || isNullSchema(a[1])) {
				for _, x := range a {
					if _, ref := asMap(x)["$ref"]; ref {
						mtm["schema"] = x
						sc = asMap(x)
					}
				}
			}
			if sc != nil && len(sc) == 0 {
				mtm["schema"] = map[string]any{"x-go-type": "json.RawMessage"}
			}
		}
	}
}

func emitNull(doc map[string]any) {
	schemas := asMap(asMap(doc["components"])["schemas"])
	for _, sc := range schemas {
		s := asMap(sc)
		required := map[string]bool{}
		if req, ok := s["required"].([]any); ok {
			for _, r := range req {
				if n, ok := r.(string); ok {
					required[n] = true
				}
			}
		}
		for name, p := range asMap(s["properties"]) {
			ps := asMap(p)
			a, ok := ps["anyOf"].([]any)
			if !ok || required[name] {
				continue
			}
			for _, x := range a {
				if isNullSchema(x) {
					ps["x-omitempty"] = false
					break
				}
			}
		}
	}
}
