package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

// PlatformWorkspaceID is the workspace the platform's own credentials live in.
const PlatformWorkspaceID = "platform"

type resolveError struct {
	kind error
	msg  string
}

func (e *resolveError) Error() string        { return e.msg }
func (e *resolveError) Is(target error) bool { return target == e.kind }
func (e *resolveError) PyType() string       { return "ModelInstanceNotFoundError" }

// Model is resolve_model_activity: the instance, its spec and provider as a run's calls need them.
func (s *Service) Model(ctx context.Context, p api.Principal, modelID string) (api.ResolvedModel, error) {
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return api.ResolvedModel{}, err
	}
	id, err := uuid.Parse(modelID)
	if err != nil {
		return api.ResolvedModel{}, &transport.PyError{Type: "ValueError", Msg: "badly formed hexadecimal UUID string"}
	}
	v, ok, err := s.instanceView(ctx, ws, id)
	if err != nil {
		return api.ResolvedModel{}, err
	}
	if !ok {
		return api.ResolvedModel{}, &resolveError{api.ErrNotFound, fmt.Sprintf("Model instance %s not found", modelID)}
	}
	if part := foreignPart(v); part != "" {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, fmt.Sprintf("Model instance %s uses a %s from another workspace", modelID, part)}
	}
	if v.Config == nil || v.Provider == nil || v.Model == nil {
		return api.ResolvedModel{}, &resolveError{api.ErrNotFound, fmt.Sprintf("Model instance %s not found", modelID)}
	}
	if !platformOffers(*v.Config, *v.Model) {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, notOffered(v.Model.ID.String(), v.Config.ID)}
	}
	if !v.IsActive {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, fmt.Sprintf("Model instance %s is inactive", modelID)}
	}
	if !v.Config.IsActive {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, fmt.Sprintf("Provider configuration %s of model instance %s is inactive", v.Config.ID, modelID)}
	}
	m := v.Model
	if m.ContextWindow == nil || *m.ContextWindow <= 0 {
		return api.ResolvedModel{}, &resolveError{api.ErrRefused, fmt.Sprintf("ModelSpec for %s has no valid context_window", modelID)}
	}
	out := api.ResolvedModel{
		ModelID: modelID, ModelName: m.ModelName, DisplayName: m.DisplayName, ProviderType: v.Provider.ProviderType, ProviderDisplayName: v.Provider.Name,
		ContextWindow: *m.ContextWindow, MaxOutputTokens: m.MaxOutputTokens,
		Prices: api.ModelPrices{
			Input: m.InputCostPerToken, Output: m.OutputCostPerToken,
			CachedInput: m.CachedInputCostPerToken, CacheCreation: m.CacheCreationInputCostPerToken,
		},
		SupportsVision: m.SupportsVision != nil && *m.SupportsVision, ReasoningLevels: m.ReasoningEfforts,
		Provider: providerProfile(*v.Provider),
	}
	if v.Config.APIKey != nil {
		out.APIKeySecret = *v.Config.APIKey
	}
	if v.Config.ManagedBy != nil {
		out.ManagedBy = *v.Config.ManagedBy
	}
	if v.Config.EndpointURL != nil {
		out.EndpointURL = *v.Config.EndpointURL
	}
	if m.DefaultContextStrategy != nil {
		out.DefaultContextStrategy = *m.DefaultContextStrategy
	}
	return out, nil
}

func foreignPart(v InstanceView) string {
	if v.Config != nil && !v.Config.PlatformManaged() && v.Config.WorkspaceID != v.WorkspaceID {
		return "provider_config"
	}
	if v.Model != nil && v.Model.WorkspaceID != v.WorkspaceID && v.Model.WorkspaceID != PlatformWorkspaceID {
		return "model_spec"
	}
	return ""
}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// providerProfile is ProviderProfile.from_mapping of the spec's contract columns.
func providerProfile(p catalogapi.ProviderSpec) api.ProviderProfile {
	return api.ProviderProfile{
		BaseURL: str(p.BaseURL), Transport: p.Transport, Auth: p.Auth, ReasoningParam: p.ReasoningParam,
		ReasoningLevels: p.ReasoningEfforts, CacheBreakpoints: p.CacheBreakpoints,
		MaxImageBytes: deref(p.MaxImageBytes), MaxImageEdge: deref(p.MaxImageEdge), PDFInput: p.PDFInput,
	}
}

func deref(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

// domainProfile is the full contract of a provider spec, models listing included.
func domainProfile(p catalogapi.ProviderSpec) (domain.Profile, error) {
	return domain.NewProfile(domain.Profile{
		BaseURL: str(p.BaseURL), Transport: p.Transport, Auth: p.Auth, ModelsPath: str(p.ModelsPath), ListShape: p.ListShape,
		ModelsQuery: str(p.ModelsQuery), ReasoningParam: p.ReasoningParam, ReasoningLevels: p.ReasoningEfforts,
		CacheBreakpoints: p.CacheBreakpoints,
	})
}

func profileOf(p api.ProviderProfile) (domain.Profile, error) {
	return domain.NewProfile(domain.Profile{
		BaseURL: p.BaseURL, Transport: p.Transport, Auth: p.Auth, ReasoningParam: p.ReasoningParam,
		ReasoningLevels: p.ReasoningLevels, CacheBreakpoints: p.CacheBreakpoints,
	})
}

// localEndpoint maps localhost the way the worker does (AGENTAREA_LOCAL_HOST).
func (s *Service) localEndpoint(u string) string {
	if u == "" || s.d.LocalHost == "" {
		return u
	}
	return strings.ReplaceAll(strings.ReplaceAll(u, "localhost", s.d.LocalHost), "127.0.0.1", s.d.LocalHost)
}

// apiKey is resolve_provider_api_key: a platform configuration's key is read from
// the platform workspace, and only for a call billing holds.
func (s *Service) apiKey(ctx context.Context, ws scope.Workspace, userID, reference, managedBy string, funded bool) (string, error) {
	if managedBy == api.ManagedByPlatform && !funded {
		return "", &transport.PyError{Type: "UnfundedPlatformCallError",
			Msg: "a call on the platform's credentials must be held by billing before its credential is read"}
	}
	if reference == "" {
		return "", nil
	}
	if managedBy == api.ManagedByPlatform {
		pw, err := scope.NewWorkspace(PlatformWorkspaceID, "")
		if err != nil {
			return "", err
		}
		ws, userID = pw, PlatformWorkspaceID
	}
	return s.readSecret(ctx, ws, userID, reference)
}

func (s *Service) readSecret(ctx context.Context, ws scope.Workspace, userID, name string) (string, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return "", err
	}
	defer release()
	v, err := s.d.Secrets.Manager(sess, userID).Get(ctx, name)
	switch {
	case errors.Is(err, ksecrets.ErrNotFound):
		return "", nil
	case errors.Is(err, ksecrets.ErrDecrypt):
		return "", &transport.PyError{Type: "ValueError", Msg: "Failed to decrypt secret. Key may have changed.", Cause: err}
	}
	return v, err
}

func (s *Service) roundTripper(managedBy string) http.RoundTripper {
	if managedBy == api.ManagedByPlatform {
		return s.d.Out.Transport(netguard.Vendor)
	}
	return s.d.Out.Transport(netguard.Member)
}

// Call is LLMExecutionService.execute's model call over a resolved model:
// the deltas streamed to OnChunk, then one reply.
func (s *Service) Call(ctx context.Context, p api.Principal, call api.Call) (api.Reply, error) {
	reply, err := s.call(ctx, p, call)
	if err != nil && !errors.Is(err, context.Canceled) {
		return api.Reply{}, transport.CallFailure(err)
	}
	return reply, err
}

func (s *Service) call(ctx context.Context, p api.Principal, call api.Call) (api.Reply, error) {
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return api.Reply{}, err
	}
	m := call.Model
	if m.Provider.Transport == "" && m.ModelID != "" {
		if m, err = s.Model(ctx, p, m.ModelID); err != nil {
			return api.Reply{}, err
		}
	}
	profile, err := profileOf(m.Provider)
	if err != nil {
		return api.Reply{}, err
	}
	levels := m.ReasoningLevels
	if len(levels) == 0 {
		levels = profile.ReasoningLevels
	}
	if err := domain.CheckEffort(call.ReasoningEffort, levels, m.ModelName); err != nil {
		return api.Reply{}, err
	}
	key, err := s.apiKey(ctx, ws, p.UserID, m.APIKeySecret, m.ManagedBy, call.Funded)
	if err != nil {
		return api.Reply{}, err
	}
	model := transport.Model{
		ProviderType: m.ProviderType, ModelName: m.ModelName, APIKey: key, EndpointURL: s.localEndpoint(m.EndpointURL),
		Prices: transport.Prices{
			Input: m.Prices.Input, Output: m.Prices.Output, CachedInput: m.Prices.CachedInput, CacheCreation: m.Prices.CacheCreation,
		},
		Profile: profile, Transport: s.roundTripper(m.ManagedBy),
	}
	return Complete(ctx, model, transport.Request{
		Messages: call.Messages, Tools: call.Tools, Temperature: call.Temperature, MaxTokens: call.MaxTokens,
		ReasoningEffort: call.ReasoningEffort, ReasoningMaxTokens: call.ReasoningMaxTokens,
	}, call.OnChunk)
}

// Complete is LLMExecutionService._call: content and thinking joined, the last
// tool-call snapshot, the max positive cost. Cancelled after the provider
// reported usage, the reply is what was billed, Interrupted.
func Complete(ctx context.Context, m transport.Model, r transport.Request, onChunk func(api.Chunk)) (api.Reply, error) {
	var content, thinking strings.Builder
	var reply api.Reply
	var usage *transport.Usage
	cost := money.MustParse("0.0")
	positive := false
	index := 0
	err := m.Stream(ctx, r, func(d transport.Delta) error {
		if d.Reasoning != "" {
			thinking.WriteString(d.Reasoning)
			if onChunk != nil {
				onChunk(api.Chunk{Delta: d.Reasoning, Thinking: true, Index: index})
				index++
			}
		}
		if d.Content != "" {
			content.WriteString(d.Content)
			if onChunk != nil {
				onChunk(api.Chunk{Delta: d.Content, Index: index})
				index++
			}
		}
		if len(d.ToolCalls) > 0 {
			reply.ToolCalls = d.ToolCalls
		}
		if d.Usage != nil {
			usage = d.Usage
		}
		if d.FinishReason != "" {
			reply.FinishReason = d.FinishReason
		}
		if d.Cost.Sign() > 0 && (!positive || d.Cost.Cmp(cost) > 0) {
			cost, positive = d.Cost, true
		}
		return nil
	})
	if err != nil {
		if ctx.Err() == nil || usage == nil || usage.Total <= 0 {
			return api.Reply{}, err
		}
		reply.Interrupted = true
	}
	reply.Content, reply.Thinking = content.String(), thinking.String()
	if usage != nil {
		reply.Usage = api.Usage(*usage)
	}
	reply.ProviderCostUSD = cost
	reply.ChunkCount = index
	return reply, nil
}
