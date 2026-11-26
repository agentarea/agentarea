// Package operator reconciles the deployment's declared custom resources (agentarea-operator
// handler.py) into platform rows: LLMProviderConfig into a provider configuration, its key and
// model instances; PlatformConnection into a platform MCP or OpenAPI connection and its token;
// PlatformEgressExit into a platform egress exit. It is the only writer of managed_by=platform.
// A resource that goes away withdraws nothing: rate cards, usage records and every workspace
// using the rows still name them.
package operator

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

// PlatformWorkspace is where platform rows live; a resource without workspaceId declares one.
const PlatformWorkspace = "platform"

// Retry delays: a temporary failure, a secret that cannot be read, a catalog entry not synced yet.
const (
	RetryDelay        = 60 * time.Second
	SecretRetryDelay  = 30 * time.Second
	CatalogRetryDelay = 600 * time.Second
)

// SecretReader reads one key of a Kubernetes Secret in namespace.
type SecretReader interface {
	Read(ctx context.Context, namespace, name, key string) (string, error)
}

// Deps are the owning modules' declaration ports, the Secret reader and the discovery client.
type Deps struct {
	Catalog     api.PlatformDeclarations
	Models      modelsapi.DeclaredProviders
	Connections connectionsapi.PlatformConnections
	Egress      governanceapi.EgressExitDeclarations
	Secrets     SecretReader
	// PlatformHTTP discovers a platform provider's models (the vendor egress), WorkspaceHTTP a
	// workspace one's (the member egress), as their model calls go.
	PlatformHTTP, WorkspaceHTTP *http.Client
	Log                         *slog.Logger
	Now                         func() time.Time
}

// Reconciler turns one resource into rows and the status to patch onto it.
type Reconciler struct{ d Deps }

// New builds the reconciler.
func New(d Deps) *Reconciler {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Reconciler{d: d}
}

// Outcome is the status patch and, when Retry is set, when to try again. A nil value in Status
// removes the field.
type Outcome struct {
	Status map[string]any
	Retry  time.Duration
}

func failed(msg string, retry time.Duration) Outcome {
	return Outcome{Status: map[string]any{"phase": "Error", "message": msg}, Retry: retry}
}

// retryError is kopf.TemporaryError: retried after delay. permanentError is kopf.PermanentError.
type retryError struct {
	msg   string
	delay time.Duration
}

func (e *retryError) Error() string { return e.msg }

type permanentError struct{ msg string }

func (e *permanentError) Error() string { return e.msg }

// errorOutcome records why and retries unless the failure is permanent.
func errorOutcome(err error) Outcome {
	if r, ok := errors.AsType[*retryError](err); ok {
		return failed(r.msg, r.delay)
	}
	if p, ok := errors.AsType[*permanentError](err); ok {
		return failed(p.msg, 0)
	}
	return failed(err.Error(), RetryDelay)
}

func (r *Reconciler) stamp() string {
	return r.d.Now().UTC().Format("2006-01-02T15:04:05.000000-07:00")
}

type secretRef struct{ namespace, name, key string }

func refOf(spec map[string]any, field string) (secretRef, bool) {
	raw, ok := spec[field].(map[string]any)
	if !ok {
		return secretRef{}, false
	}
	return secretRef{namespace: str(raw["namespace"]), name: str(raw["name"]), key: str(raw["key"])}, true
}

// readSecret reads the resource's own-namespace secret: a cross-namespace reference is a
// confused-deputy read and is refused.
func (r *Reconciler) readSecret(ctx context.Context, spec map[string]any, field, namespace string) (string, *Outcome) {
	ref, ok := refOf(spec, field)
	if !ok {
		o := failed(field+" is required", 0)
		return "", &o
	}
	if ref.namespace != "" && ref.namespace != namespace {
		o := failed(fmt.Sprintf("%s.namespace '%s' does not match this resource's own namespace '%s'; "+
			"cross-namespace secret references are not allowed", field, ref.namespace, namespace), 0)
		return "", &o
	}
	v, err := r.d.Secrets.Read(ctx, namespace, ref.name, ref.key)
	if err != nil {
		o := failed("Failed to read secret: "+err.Error(), SecretRetryDelay)
		return "", &o
	}
	return v, nil
}

// Provider is on_provider_config_change.
func (r *Reconciler) Provider(ctx context.Context, namespace, name string, spec map[string]any) Outcome {
	key, o := r.readSecret(ctx, spec, "apiKeySecretRef", namespace)
	if o != nil {
		return *o
	}
	configID, models, err := r.syncProvider(ctx, namespace, name, spec, key)
	if err != nil {
		return errorOutcome(err)
	}
	message := "Synced (no models)"
	if models > 0 {
		message = fmt.Sprintf("Synced with %d models", models)
	}
	if warning, err := r.defaultWarning(ctx); err != nil {
		return errorOutcome(err)
	} else if warning != "" {
		r.d.Log.WarnContext(ctx, "LLMProviderConfig "+namespace+"/"+name+": "+warning)
		message += "; warning: " + warning
	}
	return Outcome{Status: map[string]any{"phase": "Synced", "providerConfigId": configID.String(),
		"discoveredModels": models, "lastSyncedAt": r.stamp(), "message": message}}
}

// Rediscover is periodic_rediscovery: only resources that discover models, and a failure is
// recorded without a retry.
func (r *Reconciler) Rediscover(ctx context.Context, namespace, name string, spec map[string]any) *Outcome {
	if !truthy(spec["discoverModels"]) {
		return nil
	}
	if _, ok := refOf(spec, "apiKeySecretRef"); !ok {
		return nil
	}
	key, o := r.readSecret(ctx, spec, "apiKeySecretRef", namespace)
	if o != nil {
		if o.Retry == 0 {
			return o
		}
		return &Outcome{Status: map[string]any{"message": "Rediscovery failed: " + strings.TrimPrefix(str(o.Status["message"]), "Failed to read secret: ")}}
	}
	_, models, err := r.syncProvider(ctx, namespace, name, spec, key)
	if err != nil {
		r.d.Log.ErrorContext(ctx, "Periodic rediscovery failed", "resource", name, "error", err.Error())
		return &Outcome{Status: map[string]any{"message": "Rediscovery failed: " + err.Error()}}
	}
	return &Outcome{Status: map[string]any{"phase": "Synced", "discoveredModels": models, "lastSyncedAt": r.stamp(),
		"message": fmt.Sprintf("Re-synced with %d models", models)}}
}

func (r *Reconciler) syncProvider(ctx context.Context, namespace, name string, spec map[string]any, key string) (uuid.UUID, int, error) {
	providerKey, display := str(spec["providerKey"]), str(spec["name"])
	if providerKey == "" || display == "" {
		return uuid.Nil, 0, errors.New("spec.providerKey and spec.name are required")
	}
	workspaceID := PlatformWorkspace
	if ws := str(spec["workspaceId"]); ws != "" {
		workspaceID = ws
	}
	specID, ok, err := r.d.Catalog.ProviderSpecID(ctx, providerKey)
	if err != nil {
		return uuid.Nil, 0, err
	}
	if !ok {
		return uuid.Nil, 0, &retryError{msg: fmt.Sprintf("ProviderSpec with key '%s' not found (catalog not imported yet?)", providerKey), delay: RetryDelay}
	}
	platform := workspaceID == PlatformWorkspace
	configID := WorkspaceConfigID(workspaceID, namespace, name, providerKey)
	if platform {
		configID = PlatformConfigID(providerKey)
	}
	var endpoint *string
	if e := str(spec["endpointUrl"]); e != "" {
		endpoint = &e
	}
	var declared []api.DeclaredModelSpec
	var tags [][]string
	switch {
	case truthy(spec["discoverModels"]):
		client := r.d.WorkspaceHTTP
		if platform {
			client = r.d.PlatformHTTP
		}
		for _, m := range r.discover(ctx, client, providerKey, key, endpoint) {
			declared, tags = append(declared, m), append(tags, nil)
		}
	default:
		for _, raw := range list(spec["models"]) {
			m, t, err := explicitModel(raw)
			if err != nil {
				return uuid.Nil, 0, err
			}
			declared, tags = append(declared, m), append(tags, t)
		}
	}
	specIDs, err := r.d.Catalog.DeclareModelSpecs(ctx, workspaceID, specID, declared)
	if err != nil {
		return uuid.Nil, 0, err
	}
	d := modelsapi.ProviderDeclaration{ConfigID: configID, ProviderSpecID: specID, WorkspaceID: workspaceID, Name: display,
		EndpointURL: endpoint, IsPublic: boolOr(spec["isPublic"], true), PlatformManaged: platform, APIKey: key}
	for i, m := range declared {
		id := WorkspaceInstanceID(configID, m.ModelName)
		if platform {
			id = PlatformInstanceID(providerKey, m.ModelName)
		}
		d.Instances = append(d.Instances, modelsapi.DeclaredInstance{ID: id, ModelSpecID: specIDs[m.ModelName], Name: m.ModelName, Tags: tags[i]})
	}
	if err := r.d.Models.DeclareProvider(ctx, d); err != nil {
		return uuid.Nil, 0, err
	}
	return configID, len(declared), nil
}

// declarableKinds are the model kinds a spec.models entry may declare.
func declarableKinds() []string { return []string{"chat", "decision", "image", "video"} }

// explicitModel is one spec.models entry: the resource is the whole truth about its tags.
func explicitModel(raw any) (api.DeclaredModelSpec, []string, error) {
	em, ok := raw.(map[string]any)
	name := str(em["modelName"])
	if !ok || name == "" {
		return api.DeclaredModelSpec{}, nil, errors.New("every spec.models entry needs a modelName")
	}
	m := api.DeclaredModelSpec{ModelName: name, DisplayName: name, ContextWindow: 4096,
		SupportsVision: boolPtr(boolOr(em["supportsVision"], false)), SupportsReasoning: boolPtr(boolOr(em["supportsReasoning"], false))}
	if v := str(em["displayName"]); v != "" {
		m.DisplayName = v
	}
	if v := str(em["kind"]); v != "" {
		if !slices.Contains(declarableKinds(), v) {
			return api.DeclaredModelSpec{}, nil, fmt.Errorf("kind of %s is %q; one of %s", name, v, strings.Join(declarableKinds(), ", "))
		}
		m.Kind = v
	}
	description := str(em["description"])
	m.Description = &description
	if n, ok := integer(em["contextWindow"]); ok {
		m.ContextWindow = n
	}
	if n, ok := integer(em["maxOutputTokens"]); ok {
		m.MaxOutputTokens = &n
	}
	if raw, ok := em["reasoningEfforts"]; ok && raw != nil {
		m.ReasoningEfforts = strings_(raw)
	}
	var err error
	for field, dst := range map[string]**money.Decimal{
		"inputCostPerToken": &m.InputCostPerToken, "outputCostPerToken": &m.OutputCostPerToken,
		"cachedInputCostPerToken": &m.CachedInputCostPerToken, "cacheCreationInputCostPerToken": &m.CacheCreationInputCostPerToken,
	} {
		if *dst, err = price(em[field]); err != nil {
			return api.DeclaredModelSpec{}, nil, fmt.Errorf("%s of %s: %w", field, name, err)
		}
	}
	tags := strings_(em["tags"])
	if tags == nil {
		tags = []string{}
	}
	return m, tags, nil
}

func (r *Reconciler) defaultWarning(ctx context.Context) (string, error) {
	defaults, err := r.d.Models.PlatformDefaults(ctx)
	if err != nil || len(defaults) <= 1 {
		return "", err
	}
	return fmt.Sprintf("%d platform models are tagged default (%s); new agents start on %s. Tag exactly one.",
		len(defaults), strings.Join(defaults, ", "), defaults[0]), nil
}

// discoveryBases are the providers whose /models listing is known without an endpoint.
func discoveryBase(providerKey string) string {
	switch providerKey {
	case "openrouter":
		return "https://openrouter.ai/api"
	case "openai":
		return "https://api.openai.com"
	case "anthropic":
		return "https://api.anthropic.com"
	case "mistral":
		return "https://api.mistral.ai"
	case "groq":
		return "https://api.groq.com/openai"
	case "together":
		return "https://api.together.xyz"
	case "fireworks":
		return "https://api.fireworks.ai/inference"
	case "deepseek":
		return "https://api.deepseek.com"
	case "perplexity":
		return "https://api.perplexity.ai"
	}
	return ""
}

// discover is discover_models: the provider's /v1/models listing, none when it cannot be read.
func (r *Reconciler) discover(ctx context.Context, client *http.Client, providerKey, key string, endpoint *string) []api.DeclaredModelSpec {
	base := discoveryBase(providerKey)
	if endpoint != nil {
		base = *endpoint
	}
	if base == "" {
		r.d.Log.WarnContext(ctx, "No base URL for provider, skipping discovery", "provider", providerKey)
		return nil
	}
	base = strings.TrimRight(base, "/")
	url := base + "/v1/models"
	if strings.HasSuffix(base, "/v1") {
		url = base + "/models"
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		r.d.Log.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "error", err.Error())
		return nil
	}
	if providerKey == "anthropic" {
		req.Header.Set("x-api-key", key)
		req.Header.Set("anthropic-version", "2023-06-01")
	} else {
		req.Header.Set("Authorization", "Bearer "+key)
	}
	resp, err := client.Do(req)
	if err != nil {
		r.d.Log.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "error", err.Error())
		return nil
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		r.d.Log.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "status", resp.StatusCode)
		return nil
	}
	var listing struct {
		Data []map[string]any `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&listing); err != nil {
		r.d.Log.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "error", err.Error())
		return nil
	}
	var out []api.DeclaredModelSpec
	for _, m := range listing.Data {
		id := str(m["id"])
		display := id
		if n, ok := m["name"].(string); ok {
			display = n
		}
		description := str(m["description"])
		window := 4096
		if n, ok := integer(m["context_length"]); ok {
			window = n
		}
		out = append(out, api.DeclaredModelSpec{ModelName: id, DisplayName: display, Description: &description, ContextWindow: window})
	}
	r.d.Log.InfoContext(ctx, "Discovered models", "count", len(out), "provider", providerKey)
	return out
}

// Connection is on_platform_connection_change.
func (r *Reconciler) Connection(ctx context.Context, namespace, name string, spec map[string]any) Outcome {
	token, o := r.readSecret(ctx, spec, "tokenSecretRef", namespace)
	if o != nil {
		return *o
	}
	connectionID, serverID, err := r.syncConnection(ctx, spec, token)
	if err != nil {
		r.d.Log.ErrorContext(ctx, "PlatformConnection sync failed", "resource", namespace+"/"+name, "error", err.Error())
		return errorOutcome(err)
	}
	return r.connectionSynced(connectionID, serverID, "Synced")
}

// Resync is periodic_platform_connection_resync: a rotated Secret reaches the platform.
func (r *Reconciler) Resync(ctx context.Context, namespace, name string, spec map[string]any) *Outcome {
	token, o := r.readSecret(ctx, spec, "tokenSecretRef", namespace)
	if o != nil {
		if o.Retry == 0 {
			return o
		}
		return &Outcome{Status: map[string]any{"phase": "Error", "message": "Resync failed: " + strings.TrimPrefix(str(o.Status["message"]), "Failed to read secret: ")}}
	}
	connectionID, serverID, err := r.syncConnection(ctx, spec, token)
	if err != nil {
		r.d.Log.ErrorContext(ctx, "PlatformConnection resync failed", "resource", namespace+"/"+name, "error", err.Error())
		return &Outcome{Status: map[string]any{"phase": "Error", "message": "Resync failed: " + err.Error()}}
	}
	out := r.connectionSynced(connectionID, serverID, "Re-synced")
	return &out
}

func (r *Reconciler) connectionSynced(connectionID uuid.UUID, serverID *uuid.UUID, message string) Outcome {
	var server any
	if serverID != nil {
		server = serverID.String()
	}
	return Outcome{Status: map[string]any{"phase": "Synced", "connectionId": connectionID.String(), "mcpServerId": server,
		"lastSyncedAt": r.stamp(), "message": message}}
}

func (r *Reconciler) catalogItem(ctx context.Context, catalogID string) (uuid.UUID, map[string]any, error) {
	id, spec, ok, err := r.d.Catalog.CatalogItem(ctx, catalogID)
	if err != nil {
		return uuid.Nil, nil, err
	}
	if !ok {
		return uuid.Nil, nil, &retryError{msg: fmt.Sprintf("Catalog item '%s' not found (catalog not synced yet?)", catalogID), delay: CatalogRetryDelay}
	}
	return id, spec, nil
}

func (r *Reconciler) syncConnection(ctx context.Context, spec map[string]any, token string) (uuid.UUID, *uuid.UUID, error) {
	name, catalogID, description := str(spec["name"]), str(spec["catalogId"]), str(spec["description"])
	switch transport := spec["transport"]; transport {
	case "mcp":
		endpoint := str(spec["endpointUrl"])
		kind := str(spec["mcpTransport"])
		if kind == "" {
			kind = "streamable-http"
		}
		remotes := []any{map[string]any{"type": kind, "url": endpoint}}
		jsonSpec := map[string]any{"remotes": remotes}
		if catalogID != "" {
			_, item, err := r.catalogItem(ctx, catalogID)
			if err != nil {
				return uuid.Nil, nil, err
			}
			metadata := map[string]any{}
			if raw, ok := item["raw_spec"].(map[string]any); ok {
				if m, ok := raw["metadata"].(map[string]any); ok {
					metadata = m
				}
			}
			jsonSpec = map[string]any{"name": catalogID, "metadata": metadata, "remotes": remotes}
		}
		serverID, instanceID := PlatformMCPServerID(name), PlatformMCPInstanceID(name)
		changed, err := r.d.Catalog.DeclareMCPServer(ctx, api.PlatformMCPServer{ID: serverID, Name: name, Description: description,
			RemoteURL: endpoint, JSONSpec: jsonSpec})
		if err != nil {
			return uuid.Nil, nil, err
		}
		err = r.d.Connections.DeclareMCP(ctx, connectionsapi.DeclaredMCP{InstanceID: instanceID, ServerID: serverID, Name: name,
			Description: description, EndpointChanged: changed, Token: token})
		return instanceID, &serverID, err
	case "openapi":
		if catalogID == "" {
			return uuid.Nil, nil, &permanentError{msg: "catalogId is required when transport is openapi"}
		}
		itemID, item, err := r.catalogItem(ctx, catalogID)
		if err != nil {
			return uuid.Nil, nil, err
		}
		specURL := str(item["spec_url"])
		if specURL == "" {
			return uuid.Nil, nil, &retryError{msg: fmt.Sprintf("Catalog item '%s' has no spec_url", catalogID), delay: CatalogRetryDelay}
		}
		id := PlatformOpenAPIConnectionID(name)
		err = r.d.Connections.DeclareOpenAPI(ctx, connectionsapi.DeclaredOpenAPI{ID: id, RegistryItemID: itemID, Name: name,
			Description: description, SpecURL: specURL, BaseURL: str(spec["endpointUrl"]), Token: token})
		return id, nil, err
	default:
		return uuid.Nil, nil, &permanentError{msg: fmt.Sprintf("Unknown transport: %s", pyRepr(transport))}
	}
}

// EgressExit is on_platform_egress_exit_change.
func (r *Reconciler) EgressExit(ctx context.Context, namespace, name string, spec map[string]any) Outcome {
	exitName, via := str(spec["name"]), str(spec["via"])
	if exitName == "" || via == "" {
		return failed("spec.name and spec.via are required", RetryDelay)
	}
	var description *string
	if d, ok := spec["description"].(string); ok {
		description = &d
	}
	id := PlatformEgressExitID(exitName)
	if err := r.d.Egress.DeclareEgressExit(ctx, governanceapi.DeclaredEgressExit{ID: id, Name: exitName, Description: description,
		Via: via, RemoteDNS: boolOr(spec["remoteDns"], false)}); err != nil {
		r.d.Log.ErrorContext(ctx, "PlatformEgressExit sync failed", "resource", namespace+"/"+name, "error", err.Error())
		return failed(err.Error(), RetryDelay)
	}
	return Outcome{Status: map[string]any{"phase": "Synced", "exitId": id.String(), "lastSyncedAt": r.stamp(), "message": "Synced"}}
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func truthy(v any) bool {
	b, _ := v.(bool)
	return b
}

func boolOr(v any, def bool) bool {
	if b, ok := v.(bool); ok {
		return b
	}
	return def
}

func boolPtr(b bool) *bool { return &b }

func list(v any) []any {
	l, _ := v.([]any)
	return l
}

func strings_(v any) []string {
	l, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(l))
	for _, x := range l {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func integer(v any) (int, bool) {
	switch n := v.(type) {
	case int64:
		return int(n), true
	case int:
		return n, true
	case float64:
		return int(n), true
	}
	return 0, false
}

// price is a resource's cost per token: a number or its decimal text; absent is nil.
func price(v any) (*money.Decimal, error) {
	var text string
	switch n := v.(type) {
	case nil:
		return nil, nil
	case string:
		text = n
	case int64:
		text = strconv.FormatInt(n, 10)
	case float64:
		text = strconv.FormatFloat(n, 'f', -1, 64)
	default:
		return nil, fmt.Errorf("%v is not a number", v)
	}
	d, err := money.Parse(text)
	if err != nil {
		return nil, err
	}
	return &d, nil
}

func pyRepr(v any) string {
	switch s := v.(type) {
	case nil:
		return "None"
	case string:
		return "'" + s + "'"
	}
	return fmt.Sprint(v)
}
