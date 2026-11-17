package runtime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/gateway"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/store"
)

const managedByPlatform = "platform"

// instance is a container-backed instance with its merged spec.
type instance struct {
	ID          string
	WorkspaceID string
	Spec        map[string]any
}

// loaded is an instance as the gateway and the runtime need it.
type loaded struct {
	target    gateway.Target
	container *instance
}

func decodeObject(raw []byte, what string) (map[string]any, error) {
	out := map[string]any{}
	if len(raw) == 0 {
		return out, nil
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v map[string]any
	if err := d.Decode(&v); err != nil {
		return nil, fmt.Errorf("decode MCP %s spec: %w", what, err)
	}
	if v == nil {
		return out, nil
	}
	return v, nil
}

func (r *Runtime) loadRow(ctx context.Context, instanceID string) (store.LoadInstanceRow, error) {
	id, err := uuid.Parse(instanceID)
	if err != nil {
		return store.LoadInstanceRow{}, gateway.ErrInstanceNotFound
	}
	var row store.LoadInstanceRow
	err = r.readQ(ctx, func(s *store.Queries) error {
		var err error
		row, err = s.LoadInstance(ctx, id)
		return err
	})
	if store.IsNoRows(err) {
		return store.LoadInstanceRow{}, gateway.ErrInstanceNotFound
	}
	if err != nil {
		return store.LoadInstanceRow{}, fmt.Errorf("load MCP instance: %w", err)
	}
	return row, nil
}

// load reads the instance and its server spec (catalog's), merged as the
// manager's LoadTarget merged them.
func (r *Runtime) load(ctx context.Context, instanceID string) (loaded, error) {
	row, err := r.loadRow(ctx, instanceID)
	if err != nil {
		return loaded{}, err
	}
	ws, err := scope.NewWorkspace(row.WorkspaceID, "")
	if err != nil {
		return loaded{}, fmt.Errorf("instance %s: %w", row.InstanceID, err)
	}
	server, ok, err := r.d.Specs.Get(ctx, ws, row.ServerSpecID, catalogapi.MCPSpecGet{PlatformBacked: row.ManagedBy.String == managedByPlatform})
	if err != nil {
		return loaded{}, fmt.Errorf("load MCP server spec %s: %w", row.ServerSpecID, err)
	}
	if !ok {
		return loaded{}, gateway.ErrInstanceNotFound
	}
	instanceSpec, err := decodeObject(row.JsonSpec, "instance")
	if err != nil {
		return loaded{}, err
	}
	serverSpec := map[string]any{}
	for k, v := range server.JSONSpec {
		serverSpec[k] = v
	}
	if err := refuseReferences("server spec", serverSpec); err != nil {
		return loaded{}, err
	}
	out := loaded{target: gateway.Target{InstanceID: row.InstanceID, WorkspaceID: row.WorkspaceID}}
	switch row.Transport {
	case "docker", "command":
		spec, err := mergeContainerSpec(serverSpec, instanceSpec, row.Transport, server.Cmd, deref(server.DockerImageURL))
		if err != nil {
			return loaded{}, err
		}
		out.container = &instance{ID: row.InstanceID, WorkspaceID: row.WorkspaceID, Spec: spec}
	case "url":
		u, err := urlServer(serverSpec, instanceSpec, deref(server.RemoteURL))
		if err != nil {
			return loaded{}, fmt.Errorf("instance %s: %w", row.InstanceID, err)
		}
		if row.AuthConfigID.Valid {
			u.AuthConfigID = row.AuthConfigID.UUID.String()
		}
		u.ManagedBy = row.ManagedBy.String
		out.target.URL = u
	default:
		return loaded{}, fmt.Errorf("instance %s has transport %q, which the gateway does not serve", row.InstanceID, row.Transport)
	}
	return out, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// refuseReferences refuses a secret reference outside the instance's own
// spec: the platform authorizes a reference only against the spec carrying it.
func refuseReferences(layer string, spec map[string]any) error {
	for _, field := range []string{"environment", "headers"} {
		values, _ := spec[field].(map[string]any)
		for name, v := range values {
			if _, ok := v.(map[string]any); ok {
				return fmt.Errorf("%s %s.%s is a secret reference; only the instance's own spec may reference a workspace secret", layer, field, name)
			}
		}
	}
	return nil
}

func mergeContainerSpec(server, inst map[string]any, transport string, cmd []any, dockerImage string) (map[string]any, error) {
	spec := make(map[string]any, len(server)+len(inst))
	for k, v := range server {
		spec[k] = v
	}
	for k, v := range inst {
		spec[k] = v
	}
	instanceImage, _ := inst["image"].(string)
	switch {
	case transport == "docker" && strings.TrimSpace(instanceImage) != "":
		// An image the instance names replaces the server's invocation.
		for _, k := range []string{"args", "cmd", "endpoint_url"} {
			if _, ok := inst[k]; !ok {
				delete(spec, k)
			}
		}
	case transport == "command" && cmd != nil:
		command := make([]string, 0, len(cmd))
		for _, item := range cmd {
			s, ok := item.(string)
			if !ok {
				return nil, errors.New("decode MCP command spec")
			}
			command = append(command, s)
		}
		if len(command) == 0 {
			return nil, errors.New("decode MCP command spec")
		}
		spec["command"] = command[0]
		args := make([]any, 0, len(command)-1)
		for _, a := range command[1:] {
			args = append(args, a)
		}
		spec["args"] = args
	case transport == "docker" && dockerImage != "":
		if _, ok := spec["image"]; !ok {
			spec["image"] = dockerImage
		}
	}
	spec["type"] = transport
	return spec, nil
}

func urlServer(server, inst map[string]any, remoteURL string) (*gateway.URLServer, error) {
	merged := make(map[string]any, len(server)+len(inst))
	for k, v := range server {
		merged[k] = v
	}
	if remoteURL != "" {
		if _, ok := merged["type"]; !ok {
			merged["type"] = "url"
		}
		if _, ok := merged["endpoint_url"]; !ok {
			merged["endpoint_url"] = remoteURL
		}
	}
	normalizeURLKeys(merged)
	for k, v := range inst {
		merged[k] = v
	}
	merged["type"] = "url"
	normalizeURLKeys(merged)
	out := &gateway.URLServer{}
	switch endpoint := merged["endpoint_url"].(type) {
	case nil:
	case string:
		out.EndpointURL = endpoint
	default:
		return nil, errors.New("endpoint_url must be a string")
	}
	switch headers := merged["headers"].(type) {
	case nil:
	case map[string]any:
		out.Headers = make(map[string]any, len(headers))
		for name, v := range headers {
			switch v.(type) {
			case string, map[string]any:
			default:
				return nil, fmt.Errorf("header %q must be a string or a secret reference", name)
			}
			out.Headers[name] = v
		}
	default:
		return nil, errors.New("headers must be an object")
	}
	switch names := inst["env_vars"].(type) {
	case nil:
	case []any:
		for _, item := range names {
			name, ok := item.(string)
			if !ok {
				return nil, errors.New("env_vars must hold names")
			}
			out.EnvVars = append(out.EnvVars, name)
		}
	default:
		return nil, errors.New("env_vars must be a list")
	}
	return out, nil
}

// normalizeURLKeys moves a legacy url or external_url key to endpoint_url.
func normalizeURLKeys(spec map[string]any) {
	if spec["type"] != "url" {
		return
	}
	if endpoint, ok := spec["endpoint_url"]; ok && endpoint != nil && endpoint != "" && endpoint != false {
		return
	}
	for _, legacy := range []string{"url", "external_url"} {
		if v, ok := spec[legacy].(string); ok && strings.TrimSpace(v) != "" {
			spec["endpoint_url"] = v
			delete(spec, legacy)
			return
		}
	}
}
