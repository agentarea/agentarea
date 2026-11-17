package runtime

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

const (
	basePort          = 8080
	defaultDockerPort = 8000
	egressLabel       = "agentarea.io/egress"
	// reservedLabels prefixes the labels only the platform sets (data-plane
	// owner, egress, instance and workspace ids).
	reservedLabels    = "agentarea.io/"
	contextKeyEnv     = "MCP_CONTEXT_KEY"
	contextDerivation = "agentarea/mcp-context/v1:"
)

// SpecRefusedError is a spec the runtime will not start.
type SpecRefusedError struct{ Reason string }

func (e *SpecRefusedError) Error() string { return "MCP instance spec refused: " + e.Reason }

// FailureReason is the reason shown to the caller.
func (e *SpecRefusedError) FailureReason() string { return e.Reason }

// Secrets is the secret backend the runtime resolves workload secrets with
// (profiles/cluster/secrets.Factory).
type Secrets interface {
	Manager(s db.Session, userID string) ksecrets.Manager
	UserSecrets(s db.Session) ksecrets.UserSecrets
}

// InstanceSecretName is the name connections stores an instance's env_vars under.
func InstanceSecretName(instanceID, name string) string {
	return "mcp_instance_" + instanceID + "_" + name
}

// ContextKey is the per-instance key a workload verifies X-AgentArea-Context with.
func ContextKey(secret []byte, instanceID string) string {
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(contextDerivation + instanceID))
	return hex.EncodeToString(mac.Sum(nil))
}

// contextEnabled reads json_spec.context: only {"enabled": true} opts in.
func contextEnabled(spec map[string]any) (bool, error) {
	raw, ok := spec["context"]
	if !ok || raw == nil {
		return false, nil
	}
	v, ok := raw.(map[string]any)
	if !ok {
		return false, errors.New(`json_spec.context must be {"enabled": true}`)
	}
	enabled, ok := v["enabled"].(bool)
	if len(v) != 1 || !ok || !enabled {
		return false, errors.New(`json_spec.context must be exactly {"enabled": true}`)
	}
	return true, nil
}

// egressRequired reads json_spec.egress: only {"required": <bool>} is one.
func egressRequired(spec map[string]any) (bool, error) {
	raw, ok := spec["egress"]
	if !ok || raw == nil {
		return false, nil
	}
	v, ok := raw.(map[string]any)
	required, isBool := v["required"].(bool)
	if !ok || len(v) != 1 || !isBool {
		return false, errors.New(`json_spec.egress must be {"required": true|false}`)
	}
	return required, nil
}

// resolveSecrets reads the instance's environment references and env_vars
// from its own workspace, at the moment of use.
func (r *Runtime) resolveSecrets(ctx context.Context, workspaceID, instanceID string, refs map[string]any, names []string) (map[string]string, error) {
	ws, err := scope.NewWorkspace(workspaceID, "")
	if err != nil {
		return nil, fmt.Errorf("instance %s: %w", instanceID, err)
	}
	sess, release, err := r.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	out, err := ksecrets.ResolveValues(ctx, ksecrets.NewUserResolver(r.d.Secrets.UserSecrets(sess)), refs)
	if err != nil {
		return nil, err
	}
	if len(names) == 0 {
		return out, nil
	}
	m := r.d.Secrets.Manager(sess, "")
	for _, name := range names {
		v, err := m.Get(ctx, InstanceSecretName(instanceID, name))
		if err != nil {
			return nil, fmt.Errorf("resolve MCP secret environment %s: %w", name, err)
		}
		out[name] = v
	}
	return out, nil
}

// buildSpec turns an instance into its workload: mcp-base for a command
// instance, the image for a docker one, secrets resolved, storage and caller
// context keys issued, then the deployment's hook.
func (r *Runtime) buildSpec(ctx context.Context, inst *instance) (workload.Spec, error) {
	js := inst.Spec
	if js["type"] == "docker" && imageServesStdio(js) {
		image, _ := js["image"].(string)
		return workload.Spec{}, &SpecRefusedError{Reason: fmt.Sprintf(
			"image %s speaks stdio; an image runs only when it serves MCP over HTTP on a port, so use the server's npm or PyPI package instead", image)}
	}
	spec := workload.Spec{InstanceID: inst.ID, WorkspaceID: inst.WorkspaceID, Name: inst.ID, ServiceName: inst.ID}
	if err := r.applyTransport(&spec, js); err != nil {
		return workload.Spec{}, err
	}
	applyResourceLimits(&spec, js)
	env := map[string]any{}
	if values, ok := js["environment"].(map[string]any); ok {
		for k, v := range values {
			env[k] = v
		}
	}
	var names []string
	for _, n := range stringList(js["env_vars"]) {
		if n != "" {
			names = append(names, n)
		}
	}
	resolved, err := r.resolveSecrets(ctx, inst.WorkspaceID, inst.ID, env, names)
	if err != nil {
		return workload.Spec{}, fmt.Errorf("resolve MCP environment: %w", err)
	}
	if len(resolved) > 0 {
		spec.Environment = resolved
	}
	if labels, ok := stringMap(js["labels"]); ok {
		for k := range labels {
			if strings.HasPrefix(k, reservedLabels) {
				r.d.Log.Warn("dropping a reserved label from an instance's json_spec", "instance_id", inst.ID, "label", k)
				delete(labels, k)
			}
		}
		spec.Labels = labels
	}
	storageEnv, err := r.d.Storage.Environment(inst.ID, inst.WorkspaceID, js)
	if err != nil {
		r.d.Log.Error("MCP storage environment could not be issued", "instance_id", inst.ID, "error", err)
		return workload.Spec{}, err
	}
	mergeEnv(&spec, storageEnv)
	enabled, err := contextEnabled(js)
	if err != nil {
		return workload.Spec{}, err
	}
	if enabled {
		mergeEnv(&spec, map[string]string{contextKeyEnv: ContextKey([]byte(r.d.Config.GatewaySecret), inst.ID)})
	}
	if r.d.SpecHook != nil {
		if raw, ok := js["egress_exit"]; ok && raw != nil {
			exit, isName := raw.(string)
			if !isName {
				return workload.Spec{}, errors.New("json_spec.egress_exit must be an egress exit id")
			}
			spec.EgressExit = exit
		}
		if spec.EgressRequired, err = egressRequired(js); err != nil {
			return workload.Spec{}, err
		}
		if err := r.d.SpecHook(ctx, inst.ID, inst.WorkspaceID, &spec); err != nil {
			r.d.Log.Error("instance spec hook refused the instance", "instance_id", inst.ID, "error", err)
			return workload.Spec{}, fmt.Errorf("instance spec hook: %w", err)
		}
	}
	return spec, nil
}

func mergeEnv(spec *workload.Spec, extra map[string]string) {
	if len(extra) == 0 {
		return
	}
	if spec.Environment == nil {
		spec.Environment = make(map[string]string, len(extra))
	}
	for k, v := range extra {
		spec.Environment[k] = v
	}
}

func (r *Runtime) applyTransport(spec *workload.Spec, js map[string]any) error {
	if js["type"] == "command" {
		cmd, _ := js["command"].(string)
		spec.Image = r.d.Config.BaseImage
		spec.Port = basePort
		spec.Command = append([]string{cmd}, stringList(js["args"])...)
		return nil
	}
	if image, ok := js["image"].(string); ok {
		spec.Image = image
	}
	port, err := instancePort(js)
	if err != nil {
		return err
	}
	spec.Port = port
	spec.Command = dockerArgv(js)
	return nil
}

// instancePort is the port a docker workload serves on, 8000 when undeclared.
func instancePort(js map[string]any) (int, error) {
	if js["type"] == "command" {
		return basePort, nil
	}
	raw, ok := js["port"]
	if !ok || raw == nil {
		return defaultDockerPort, nil
	}
	var port int
	switch v := raw.(type) {
	case json.Number:
		n, err := strconv.Atoi(v.String())
		if err != nil {
			return 0, fmt.Errorf("MCP instance port %v is not an integer", v)
		}
		port = n
	case float64:
		port = int(v)
		if float64(port) != v {
			return 0, fmt.Errorf("MCP instance port %v is not an integer", v)
		}
	case int:
		port = v
	default:
		return 0, fmt.Errorf("MCP instance port %v is not a number", raw)
	}
	if port <= 0 || port > 65535 {
		return 0, fmt.Errorf("MCP instance port %d is outside 1-65535", port)
	}
	return port, nil
}

func applyResourceLimits(spec *workload.Spec, js map[string]any) {
	if res, ok := js["resources"].(map[string]any); ok {
		if limits, ok := res["limits"].(map[string]any); ok {
			if m, ok := limits["memory"].(string); ok {
				spec.Resources.Limits.Memory = m
			}
			if c, ok := limits["cpu"].(string); ok {
				spec.Resources.Limits.CPU = c
			}
		}
	}
	if res, ok := js["resource_limits"].(map[string]any); ok {
		if m, ok := res["memory"].(string); ok {
			spec.Resources.Limits.Memory = m
		}
		switch c := res["cpu"].(type) {
		case string:
			spec.Resources.Limits.CPU = c
		case json.Number:
			if f, err := c.Float64(); err == nil {
				spec.Resources.Limits.CPU = fmt.Sprintf("%f", f)
			}
		case float64:
			spec.Resources.Limits.CPU = fmt.Sprintf("%f", c)
		}
	}
}

func stringMap(raw any) (map[string]string, bool) {
	values, ok := raw.(map[string]any)
	if !ok {
		return nil, false
	}
	out := make(map[string]string, len(values))
	for k, v := range values {
		out[k] = fmt.Sprintf("%v", v)
	}
	return out, true
}

func stringList(raw any) []string {
	items, ok := raw.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// dockerArgv is the container argv: cmd (or command), then args, without
// the --transport=stdio a catalog entry carries for stdio clients.
func dockerArgv(js map[string]any) []string {
	var argv []string
	for _, key := range []string{"cmd", "command"} {
		switch v := js[key].(type) {
		case string:
			if v != "" {
				argv = append(argv, v)
			}
		case []any:
			argv = append(argv, stringList(v)...)
		default:
			continue
		}
		break
	}
	argv = append(argv, stringList(js["args"])...)
	kept := make([]string, 0, len(argv))
	for _, a := range argv {
		if a != "--transport=stdio" {
			kept = append(kept, a)
		}
	}
	if len(kept) == 0 {
		return nil
	}
	return kept
}

// imageServesStdio reports a docker spec whose OCI package declares stdio
// and which names no port.
func imageServesStdio(js map[string]any) bool {
	if js["port"] != nil {
		return false
	}
	image, _ := js["image"].(string)
	packages, _ := js["packages"].([]any)
	var images []map[string]any
	for _, raw := range packages {
		if pkg, ok := raw.(map[string]any); ok && pkg["registryType"] == "oci" {
			images = append(images, pkg)
		}
	}
	var chosen map[string]any
	for _, pkg := range images {
		id, _ := pkg["identifier"].(string)
		if id != "" && imageName(id) == imageName(image) {
			chosen = pkg
			break
		}
	}
	if chosen == nil && len(images) == 1 {
		chosen = images[0]
	}
	transport, _ := chosen["transport"].(map[string]any)
	return transport["type"] == "stdio"
}

func imageName(ref string) string {
	if at := strings.Index(ref, "@"); at >= 0 {
		ref = ref[:at]
	}
	if colon := strings.LastIndex(ref, ":"); colon > strings.LastIndex(ref, "/") {
		ref = ref[:colon]
	}
	return ref
}
