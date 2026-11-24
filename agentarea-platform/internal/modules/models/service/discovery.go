package service

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

// DiscoveryTimeout is ModelDiscoveryService's timeout.
const DiscoveryTimeout = 30 * time.Second

// Discovered is DiscoveredModel; Kind "" is a listing no surface takes.
type Discovered struct {
	ModelName, DisplayName                                     string
	DisplayNameNull                                            bool
	ContextWindow, MaxOutputTokens                             *int
	Description                                                *string
	Input, Output, CachedInput, CacheCreation                  *money.Decimal
	SupportsFunctionCalling, SupportsVision, SupportsReasoning bool
	Kind                                                       string
}

// Skipped is SkippedModelResponse.
type Skipped struct {
	ModelName string
	Missing   []string
}

// DiscoveredRow is one written model of a discovery answer.
type DiscoveredRow struct {
	Discovered
	ID    string
	IsNew bool
}

// Discovery is DiscoveryResponse / DiscoverPreviewResponse.
type Discovery struct {
	Models  []DiscoveredRow
	New     int
	Skipped []Skipped
}

func kindByOutput() [][2]string {
	return [][2]string{{"decisions", "decision"}, {"embeddings", "embedding"}, {"video", "video"}, {"image", "image"}, {"text", "chat"}}
}

func kindFromListing(entry map[string]any) string {
	arch, ok := entry["architecture"].(map[string]any)
	if !ok {
		return "chat"
	}
	outputs, ok := arch["output_modalities"].([]any)
	if !ok {
		return "chat"
	}
	for _, kv := range kindByOutput() {
		if slices.Contains(outputs, any(kv[0])) {
			return kv[1]
		}
	}
	return ""
}

func readsImages(entry map[string]any) bool {
	arch, _ := entry["architecture"].(map[string]any)
	inputs, ok := arch["input_modalities"].([]any)
	return ok && slices.Contains(inputs, any("image"))
}

func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case string:
		return t != ""
	case json.Number:
		f, err := t.Float64()
		return err != nil || f != 0
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	}
	return true
}

func or(a, b any) any {
	if truthy(a) {
		return a
	}
	return b
}

// positiveInt is _positive_int_or_none: int(value) when it is > 0.
func positiveInt(v any) *int {
	var n int64
	switch t := v.(type) {
	case bool:
		if !t {
			return nil
		}
		n = 1
	case json.Number:
		if i, err := strconv.ParseInt(string(t), 10, 64); err == nil {
			n = i
		} else if f, err := strconv.ParseFloat(string(t), 64); err == nil && !math.IsInf(f, 0) && !math.IsNaN(f) {
			n = int64(f)
		} else {
			return nil
		}
	case string:
		i, err := strconv.ParseInt(strings.TrimSpace(t), 10, 64)
		if err != nil {
			return nil
		}
		n = i
	default:
		return nil
	}
	if n <= 0 || n > math.MaxInt32 {
		return nil
	}
	x := int(n)
	return &x
}

// nonNegativeMoney is _nonnegative_money_or_none.
func nonNegativeMoney(v any) *money.Decimal {
	var text string
	switch t := v.(type) {
	case json.Number:
		text = transport.PyNumberStr(t)
	case string:
		text = t
	default:
		return nil
	}
	d, err := money.Parse(text)
	if err != nil || d.Sign() < 0 {
		return nil
	}
	return &d
}

func parseListing(p domain.Profile, data map[string]any) ([]Discovered, error) {
	var out []Discovered
	if p.ListShape == domain.ListModelsName {
		list, _ := or(data["models"], []any{}).([]any)
		for _, x := range list {
			m, ok := x.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("listing entry is not an object")
			}
			name, _ := m["name"].(string)
			out = append(out, Discovered{ModelName: name, DisplayName: name, Kind: "chat"})
		}
		return out, nil
	}
	raw, present := data["data"]
	if !present {
		raw = []any{}
	}
	list, ok := raw.([]any)
	if !ok {
		return nil, fmt.Errorf("listing data is not a list")
	}
	for _, x := range list {
		m, ok := x.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("listing entry is not an object")
		}
		id, _ := m["id"].(string)
		if id == "" {
			continue
		}
		pricing, _ := m["pricing"].(map[string]any)
		top, _ := m["top_provider"].(map[string]any)
		d := Discovered{
			ModelName: id, DisplayName: id,
			ContextWindow:   positiveInt(or(m["context_length"], m["max_model_len"])),
			MaxOutputTokens: positiveInt(or(m["max_output_tokens"], top["max_completion_tokens"])),
			Input:           nonNegativeMoney(pricing["prompt"]), Output: nonNegativeMoney(pricing["completion"]),
			CachedInput: nonNegativeMoney(pricing["input_cache_read"]), CacheCreation: nonNegativeMoney(pricing["input_cache_write"]),
			SupportsVision: readsImages(m), Kind: kindFromListing(m),
		}
		if v, present := m["name"]; present {
			if s, ok := v.(string); ok {
				d.DisplayName = s
			} else {
				d.DisplayName, d.DisplayNameNull = "", true
			}
		}
		if v, present := m["description"]; present {
			if s, ok := v.(string); ok {
				d.Description = &s
			}
		} else {
			empty := ""
			d.Description = &empty
		}
		out = append(out, d)
	}
	return out, nil
}

// discover is ModelDiscoveryService.discover: every failure is logged and lists nothing.
func (s *Service) discover(ctx context.Context, providerKey, apiKey, endpointURL string, p domain.Profile) []Discovered {
	u := p.ModelsURL(endpointURL)
	if u == "" {
		slog.WarnContext(ctx, "No base URL for provider and no endpoint_url provided", "provider", providerKey)
		return nil
	}
	dest := netguard.Vendor
	if endpointURL != "" {
		dest = netguard.Member
	}
	client := &http.Client{Transport: s.d.Out.Transport(dest), Timeout: DiscoveryTimeout, CheckRedirect: transport.NoRedirects}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		slog.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "error", err)
		return nil
	}
	for k, v := range p.Headers(apiKey) {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		slog.WarnContext(ctx, "Model discovery failed", "provider", providerKey, "error_type", fmt.Sprintf("%T", err))
		return nil
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		slog.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "status", resp.StatusCode)
		return nil
	}
	dec := json.NewDecoder(io.LimitReader(resp.Body, discoveryBodyLimit))
	dec.UseNumber()
	var data map[string]any
	if err := dec.Decode(&data); err != nil {
		slog.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "error", err)
		return nil
	}
	models, err := parseListing(p, data)
	if err != nil {
		slog.ErrorContext(ctx, "Model discovery failed", "provider", providerKey, "error", err)
		return nil
	}
	slog.InfoContext(ctx, "Discovered models", "count", len(models), "provider", providerKey)
	return models
}

// discoveryBodyLimit bounds a provider's model listing.
const discoveryBodyLimit = 8 << 20

func missingRuntime(d Discovered) []string {
	if d.Kind == "" {
		return []string{"kind"}
	}
	if d.Kind != "chat" && d.Kind != "embedding" {
		return []string{}
	}
	if d.ContextWindow == nil {
		return []string{"context_window"}
	}
	return []string{}
}

func noneDiscovered(key string) error {
	return &HTTPError{Status: 400, Detail: fmt.Sprintf("No models discovered for provider '%s'. The provider may not support model listing or the API key may be invalid.", key)}
}

func (s *Service) persistDiscovered(ctx context.Context, providerKey string, providerSpecID uuid.UUID, found []Discovered) (Discovery, error) {
	if len(found) == 0 {
		return Discovery{}, noneDiscovered(providerKey)
	}
	var usable []Discovered
	skipped := []Skipped{}
	for _, d := range found {
		if miss := missingRuntime(d); len(miss) > 0 {
			skipped = append(skipped, Skipped{ModelName: d.ModelName, Missing: miss})
		} else {
			usable = append(usable, d)
		}
	}
	if len(skipped) > 0 {
		names := make([]string, len(skipped))
		for i, sk := range skipped {
			names[i] = sk.ModelName + " (" + strings.Join(sk.Missing, ", ") + ")"
		}
		slog.WarnContext(ctx, "Discovery skipped models missing runtime metadata", "provider", providerKey, "count", len(skipped), "models", strings.Join(names, ", "))
	}
	if len(usable) == 0 {
		return Discovery{}, &HTTPError{Status: 422, Detail: fmt.Sprintf(
			"No model discovered for provider '%s' carries the runtime metadata required to execute it (%d skipped). Configure the model specs explicitly.",
			providerKey, len(skipped))}
	}
	ws, userID, err := caller(ctx)
	if err != nil {
		return Discovery{}, err
	}
	if err := s.admin(ctx); err != nil {
		return Discovery{}, err
	}
	rows := make([]catalogapi.DiscoveredSpec, len(usable))
	for i, d := range usable {
		display := d.DisplayName
		if display == "" {
			display = d.ModelName
		}
		var desc *string
		if d.Description != nil && *d.Description != "" {
			desc = d.Description
		}
		rows[i] = catalogapi.DiscoveredSpec{
			ModelName: d.ModelName, DisplayName: display, Description: desc, Kind: d.Kind,
			ContextWindow: d.ContextWindow, MaxOutputTokens: d.MaxOutputTokens,
			InputCostPerToken: d.Input, OutputCostPerToken: d.Output, CachedInputCostPerToken: d.CachedInput,
			CacheCreationInputCostPerToken: d.CacheCreation,
			SupportsFunctionCalling:        d.SupportsFunctionCalling, SupportsVision: d.SupportsVision, SupportsReasoning: d.SupportsReasoning,
		}
	}
	written, err := s.d.Catalog.UpsertModelSpecs(ctx, ws, userID, providerSpecID, rows)
	if err != nil {
		return Discovery{}, err
	}
	out := Discovery{Skipped: skipped}
	for _, d := range usable {
		w := written[d.ModelName]
		out.Models = append(out.Models, DiscoveredRow{Discovered: d, ID: w.ID.String(), IsNew: w.IsNew})
	}
	for _, w := range written {
		if w.IsNew {
			out.New++
		}
	}
	slog.InfoContext(ctx, "Discovery for provider", "provider", providerKey, "found", len(out.Models), "new", out.New)
	return out, nil
}

// DiscoverPreview is discover_models_preview: not a dry run, the specs are written.
func (s *Service) DiscoverPreview(ctx context.Context, providerKey string, apiKey, endpointURL *string) (Discovery, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return Discovery{}, err
	}
	if err := s.admin(ctx); err != nil {
		return Discovery{}, err
	}
	spec, ok, err := s.d.Catalog.ProviderSpecByKey(ctx, ws, providerKey)
	if err != nil {
		return Discovery{}, err
	}
	if !ok {
		return Discovery{}, &HTTPError{Status: 404, Detail: fmt.Sprintf("Provider '%s' not found", providerKey)}
	}
	p, err := domainProfile(spec)
	if err != nil {
		return Discovery{}, err
	}
	if p.Auth == domain.AuthChatGPT {
		return Discovery{}, noChatGPTDiscovery()
	}
	found := s.discover(ctx, providerKey, str(apiKey), str(endpointURL), p)
	return s.persistDiscovered(ctx, providerKey, spec.ID, found)
}

// DiscoverConfig is discover_models for a saved configuration.
func (s *Service) DiscoverConfig(ctx context.Context, id uuid.UUID) (Discovery, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return Discovery{}, err
	}
	if err := s.admin(ctx); err != nil {
		return Discovery{}, err
	}
	v, ok, err := s.view(ctx, ws, id)
	if err != nil {
		return Discovery{}, err
	}
	if !ok {
		return Discovery{}, &HTTPError{Status: 404, Detail: "Provider configuration not found"}
	}
	if v.PlatformManaged() {
		return Discovery{}, &HTTPError{Status: 403, Detail: "Model discovery is not available for platform-supplied providers."}
	}
	if v.Spec == nil {
		return Discovery{}, fmt.Errorf("provider spec %s of configuration %s is missing", v.ProviderSpecID, v.ID)
	}
	key := ""
	if v.APIKey != nil && *v.APIKey != "" {
		if key, err = s.readSecret(ctx, ws, userID, *v.APIKey); err != nil {
			return Discovery{}, err
		}
	}
	p, err := domainProfile(*v.Spec)
	if err != nil {
		return Discovery{}, err
	}
	if p.Auth == domain.AuthChatGPT {
		return Discovery{}, noChatGPTDiscovery()
	}
	found := s.discover(ctx, v.Spec.ProviderKey, key, str(v.EndpointURL), p)
	return s.persistDiscovered(ctx, v.Spec.ProviderKey, v.Spec.ID, found)
}

func noChatGPTDiscovery() error {
	return &HTTPError{Status: 400, Detail: "A ChatGPT subscription offers the models the catalog lists; it has no discovery."}
}
