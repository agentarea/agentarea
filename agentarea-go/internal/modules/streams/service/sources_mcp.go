package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// mcpEventsConfig is the config of an MCP Events source: an instance of this workspace the caller
// may use, authenticating with its own headers, that offers the event in the source's mode with
// arguments its input schema takes.
func (s *Service) mcpEventsConfig(ctx context.Context, c authn.Caller, n NewSource) (map[string]any, error) {
	config := make(map[string]any, len(n.Config))
	for k, v := range n.Config {
		config[k] = v
	}
	id, err := domain.CanonicalUUID(n.Config["mcp_instance_id"])
	if err != nil {
		return nil, domain.Refused("mcp_instance_id is not an id")
	}
	if s.d.MCPEventSources == nil {
		return nil, domain.Refused(fmt.Sprintf("MCP server %s not found", id))
	}
	inst, ok, err := s.d.MCPEventSources.MCPEventSource(ctx, c.Workspace, id)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, domain.Refused(fmt.Sprintf("MCP server %s not found", id))
	}
	if err := s.perms.Require(ctx, c, "use_connection", "mcp_instance", id); err != nil {
		return nil, err
	}
	if inst.AuthConfigID != nil {
		return nil, domain.Refused("This MCP server signs in through an auth config; MCP Events sources take " +
			"servers that authenticate with their own headers")
	}
	if inst.ManagedBy != nil && *inst.ManagedBy == "platform" {
		return nil, domain.Refused("A platform-managed MCP server cannot be an event source")
	}
	args, err := parseArguments(n.Config["arguments"])
	if err != nil {
		return nil, err
	}
	if err := checkEventSource(inst.Events, n.Config["event"], args, n.Kind); err != nil {
		return nil, err
	}
	config["mcp_instance_id"] = id
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(args); err != nil {
		return nil, err
	}
	config["arguments"] = strings.TrimRight(buf.String(), "\n")
	return config, nil
}

func parseArguments(raw string) (map[string]any, error) {
	if raw == "" {
		return map[string]any{}, nil
	}
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil || dec.More() {
		return nil, domain.Refused("arguments must be a JSON object")
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, domain.Refused("arguments must be a JSON object")
	}
	return m, nil
}

func checkEventSource(record map[string]any, event string, args map[string]any, mode string) error {
	listed, ok := record["events"].([]any)
	if record == nil || !ok {
		return domain.Refused("This MCP server does not offer MCP Events; verify it again if it does now")
	}
	if e, has := record["error"]; has && e != nil && e != "" {
		text, _ := domain.Scalar(e)
		return domain.Refused("The MCP server offers events but listing them failed: " + text)
	}
	offered := map[string]map[string]any{}
	for _, t := range listed {
		if m, isMap := t.(map[string]any); isMap {
			if name, isText := m["name"].(string); isText {
				offered[name] = m
			}
		}
	}
	et, ok := offered[event]
	if !ok {
		names := make([]string, 0, len(offered))
		for n := range offered {
			names = append(names, n)
		}
		sort.Strings(names)
		return domain.Refused(fmt.Sprintf("The MCP server has no event %s; it offers %s", domain.PyRepr(event), pyList(names)))
	}
	var delivery []string
	if list, isList := et["delivery"].([]any); isList {
		for _, m := range list {
			if s, isText := m.(string); isText {
				delivery = append(delivery, s)
			}
		}
	}
	found := false
	for _, m := range delivery {
		found = found || m == mode
	}
	if !found {
		by := strings.Join(delivery, " or ")
		if by == "" {
			by = "no mode"
		}
		return domain.Refused(fmt.Sprintf("%s is delivered by %s only, not %s", domain.PyRepr(event), by, mode))
	}
	if schema, isMap := et["inputSchema"].(map[string]any); isMap {
		if where, msg, bad := schemaProblem(schema, args); bad {
			prefix := ""
			if where != "" {
				prefix = where + ": "
			}
			return domain.Refused(fmt.Sprintf("arguments for %s: %s%s", domain.PyRepr(event), prefix, msg))
		}
	}
	return nil
}

// schemaProblem checks the arguments against the top level of an input schema: required
// properties, additionalProperties false, and each property's JSON type.
func schemaProblem(schema, args map[string]any) (string, string, bool) {
	if req, ok := schema["required"].([]any); ok {
		for _, r := range req {
			if name, isText := r.(string); isText {
				if _, has := args[name]; !has {
					return "", domain.PyRepr(name) + " is a required property", true
				}
			}
		}
	}
	props, _ := schema["properties"].(map[string]any)
	keys := make([]string, 0, len(args))
	for k := range args {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if ap, ok := schema["additionalProperties"].(bool); ok && !ap {
		var extra []string
		for _, k := range keys {
			if _, known := props[k]; !known {
				extra = append(extra, domain.PyRepr(k))
			}
		}
		if len(extra) == 1 {
			return "", "Additional properties are not allowed (" + extra[0] + " was unexpected)", true
		}
		if len(extra) > 1 {
			return "", "Additional properties are not allowed (" + strings.Join(extra, ", ") + " were unexpected)", true
		}
	}
	for _, k := range keys {
		p, _ := props[k].(map[string]any)
		want, isText := p["type"].(string)
		if !isText || jsonType(args[k], want) {
			continue
		}
		return k, fmt.Sprintf("%v is not of type %s", reprJSON(args[k]), domain.PyRepr(want)), true
	}
	return "", "", false
}

func jsonType(v any, want string) bool {
	switch want {
	case "string":
		_, ok := v.(string)
		return ok
	case "boolean":
		_, ok := v.(bool)
		return ok
	case "object":
		_, ok := v.(map[string]any)
		return ok
	case "array":
		_, ok := v.([]any)
		return ok
	case "null":
		return v == nil
	case "number":
		_, ok := v.(json.Number)
		return ok
	case "integer":
		n, ok := v.(json.Number)
		if !ok {
			return false
		}
		if _, err := n.Int64(); err == nil {
			return true
		}
		f, err := n.Float64()
		return err == nil && f == float64(int64(f))
	}
	return true
}

func reprJSON(v any) string {
	if s, ok := v.(string); ok {
		return domain.PyRepr(s)
	}
	b, _ := json.Marshal(v)
	return string(b)
}
