package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/mcpclient"
)

// Verification timing (verification.py).
const (
	listAttemptTimeout = 5 * time.Second
	listRetryDelay     = 5 * time.Second
	// verifySafetyDeadline caps a verification that keeps failing transiently;
	// an in_progress older than it is stale.
	verifySafetyDeadline = 600 * time.Second
)

const (
	urlConnectFailed = "Could not connect to the MCP server"
	eventsExtension  = "io.modelcontextprotocol/events"
	maxEventPages    = 20
	maxEventTypes    = 500
	eraVerdictTTL    = 24 * time.Hour
)

// Verification error codes.
const (
	CodeInstanceNotFound     = "instance_not_found"
	CodeServerSpecNotFound   = "server_spec_not_found"
	CodeUpstreamUnauthorized = "upstream_unauthorized"
	CodeMCPError             = "mcp_error"
	CodeListToolsTimeout     = "list_tools_timeout"
	CodeSecretUnresolved     = "secret_unresolved"
	CodeOAuthReauthRequired  = "oauth_reauth_required"
	CodeAuthRequired         = "auth_required"
	CodeInterrupted          = "verification_interrupted"
)

func (s *Service) payload(status string, e *domain.VerificationError) domain.Verification {
	at := s.d.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00")
	return domain.Verification{SchemaVersion: domain.VerificationSchema, Status: status, At: &at, Error: e}
}

func failure(code, message string, detail any) *domain.VerificationError {
	return &domain.VerificationError{Code: code, Message: message, Detail: detail}
}

// isAuthFailure is _is_auth_error_payload: an upstream 401/403, by code or,
// for a transport that did not report the status, by message.
func isAuthFailure(v domain.Verification) bool {
	if v.Status != domain.VerifyFailed || v.Error == nil {
		return false
	}
	if v.Error.Code == CodeUpstreamUnauthorized {
		return true
	}
	for _, m := range []string{"401", "403", "Unauthorized", "Forbidden"} {
		if strings.Contains(v.Error.Message, m) {
			return true
		}
	}
	return false
}

// staleInProgress: an in_progress whose run must have died.
func (s *Service) staleInProgress(v domain.Verification) bool {
	if v.At == nil {
		return true
	}
	started, err := parseISO(*v.At)
	if err != nil {
		return true
	}
	return s.d.Now().Sub(started) > verifySafetyDeadline
}

func parseISO(at string) (time.Time, error) {
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999", "2006-01-02T15:04:05"} {
		if t, err := time.Parse(layout, at); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("not an ISO time: %q", at)
}

// Verify is verify_instance (a user's Verify): the state machine forced, the
// instance's secret and auth headers sent, one forced OAuth refresh and retry
// on an upstream 401/403. A bundle's state is derived, not stored. The
// result is the stored verification, success or not.
func (s *Service) Verify(ctx context.Context, ws scope.Workspace, id uuid.UUID, force bool) (domain.Verification, error) {
	inst, err := s.instanceIn(ctx, ws, id)
	if err != nil {
		return domain.Verification{}, err
	}
	if inst.PlatformManaged() {
		return domain.Verification{}, &domain.Forbidden{Msg: inst.Name + " is managed by the platform"}
	}
	return s.verifyInstance(ctx, ws, inst, force)
}

func (s *Service) instanceIn(ctx context.Context, ws scope.Workspace, id uuid.UUID) (domain.Instance, error) {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return domain.Instance{}, err
	}
	defer release()
	inst, ok, err := s.d.Instances.Get(ctx, sess, id)
	if err != nil {
		return domain.Instance{}, err
	}
	if !ok {
		return domain.Instance{}, ErrInstanceNotFound()
	}
	return inst, nil
}

func (s *Service) verifyInstance(ctx context.Context, ws scope.Workspace, inst domain.Instance, force bool) (domain.Verification, error) {
	id := uuid.MustParse(inst.ID)
	if inst.Transport == domain.TransportBundle {
		return s.bundleVerification(ctx, ws, inst)
	}
	secret, err := s.secretHeaders(ctx, ws, inst)
	var unresolved *secretUnresolved
	if errors.As(err, &unresolved) {
		s.d.Log.Warn("MCP instance cannot resolve a secret reference", "instance_id", inst.ID, "error", err)
		return s.store(ctx, ws, id, s.payload(domain.VerifyFailed, failure(CodeSecretUnresolved, err.Error(), nil)))
	}
	if err != nil {
		return domain.Verification{}, err
	}
	headers := func(refresh bool) (http.Header, error) {
		h := http.Header{}
		for k, v := range secret {
			h.Set(k, v)
		}
		dest, err := s.authDestination(ctx, ws, inst)
		if err != nil {
			return nil, err
		}
		auth, err := s.authHeaders(ctx, ws, inst, dest, refresh)
		if err != nil {
			return nil, err
		}
		for k, v := range auth {
			h.Set(k, v)
		}
		return h, nil
	}
	h, err := headers(false)
	if reauth := (*domain.ReauthRequired)(nil); errors.As(err, &reauth) {
		return s.storeReauth(ctx, ws, id), nil
	}
	if err != nil {
		return domain.Verification{}, err
	}
	v, err := s.verifyRow(ctx, ws, id, h, force)
	if err != nil || inst.AuthConfigID == nil || !isAuthFailure(v) {
		return v, err
	}
	h, err = headers(true)
	if reauth := (*domain.ReauthRequired)(nil); errors.As(err, &reauth) {
		return s.storeReauth(ctx, ws, id), nil
	}
	if err != nil {
		return domain.Verification{}, err
	}
	return s.verifyRow(ctx, ws, id, h, force)
}

// authDestination is the endpoint the auth config's headers are for.
func (s *Service) authDestination(ctx context.Context, ws scope.Workspace, inst domain.Instance) (string, error) {
	if inst.AuthConfigID == nil {
		return "", nil
	}
	if domain.IsContainer(inst.Transport) {
		return gatewayURL(inst.ID), nil
	}
	spec, ok, err := s.serverSpec(ctx, ws, inst)
	if err != nil || !ok {
		return "", err
	}
	u, _ := transportSpec(spec, inst)["endpoint_url"].(string)
	return u, nil
}

func (s *Service) bundleVerification(ctx context.Context, ws scope.Workspace, bundle domain.Instance) (domain.Verification, error) {
	var ids []uuid.UUID
	for _, m := range domain.StringList(bundle.JSONSpec["members"]) {
		if id, err := uuid.Parse(m); err == nil {
			ids = append(ids, id)
		}
	}
	members := map[string]domain.Instance{}
	if len(ids) > 0 {
		sess, release, err := s.d.DB.Read(ctx, ws)
		if err != nil {
			return domain.Verification{}, err
		}
		members, err = s.d.Instances.GetMany(ctx, sess, ids)
		release()
		if err != nil {
			return domain.Verification{}, err
		}
	}
	return domain.DeriveBundleVerification(bundle, members, s.d.Now()), nil
}

// store writes v and returns it.
func (s *Service) store(ctx context.Context, ws scope.Workspace, id uuid.UUID, v domain.Verification) (domain.Verification, error) {
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		_, err := s.d.Instances.SetVerification(ctx, tx, id, v)
		return err
	})
	return v, err
}

func (s *Service) storeReauth(ctx context.Context, ws scope.Workspace, id uuid.UUID) domain.Verification {
	v := s.payload(domain.VerifyFailed, failure(CodeOAuthReauthRequired,
		"OAuth session expired or was revoked. Reconnect with OAuth.", nil))
	if _, err := s.store(ctx, ws, id, v); err != nil {
		s.d.Log.Warn("Failed to persist reauth state", "instance_id", id, "error", err)
	}
	return v
}

// discovery is what a verification learned: tools, and the events offered.
type discovery struct {
	tools  []any
	events map[string]any
}

// verifyRow is verify(): lock the row, flip it to in_progress (unless a
// fresh one runs and force is off), list tools outside the lock with
// retries on transient failures, then write the terminal state.
func (s *Service) verifyRow(ctx context.Context, ws scope.Workspace, id uuid.UUID, extra http.Header, force bool) (domain.Verification, error) {
	var inst domain.Instance
	var merged map[string]any
	var result *domain.Verification
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		locked, ok, err := s.d.Instances.Lock(ctx, tx, id)
		if err != nil {
			return err
		}
		if !ok {
			v := s.payload(domain.VerifyFailed, failure(CodeInstanceNotFound,
				"Instance was deleted before verification could start.", nil))
			result = &v
			return nil
		}
		if locked.Transport == domain.TransportBundle {
			return &domain.Invalid{Msg: "Bundle verification is derived at read time"}
		}
		spec, found, err := s.serverSpec(ctx, ws, locked)
		if err != nil {
			return err
		}
		if !found {
			v := s.payload(domain.VerifyFailed, failure(CodeServerSpecNotFound,
				"Referenced MCP server spec was not found.", locked.ServerSpecID))
			result = &v
			_, err := s.d.Instances.SetVerification(ctx, tx, id, v)
			if err == nil {
				s.countCheck(v)
			}
			return err
		}
		if locked.Verification.Status == domain.VerifyInProgress && !force && !s.staleInProgress(locked.Verification) {
			v := locked.Verification
			result = &v
			return nil
		}
		inst, merged = locked, transportSpec(spec, locked)
		_, err = s.d.Instances.SetVerification(ctx, tx, id, s.payload(domain.VerifyInProgress, nil))
		return err
	})
	if err != nil || result != nil {
		if result != nil {
			return *result, err
		}
		return domain.Verification{}, err
	}
	// The row must reach a terminal state even when the caller goes away.
	work := context.WithoutCancel(ctx)
	v := s.probeRow(work, inst, merged, extra)
	err = s.d.DB.Write(work, ws, func(ctx context.Context, tx db.Session) error {
		var err error
		if v.d != nil {
			_, err = s.d.Instances.SetDiscovery(ctx, tx, id, v.v, v.d.tools, v.d.events)
		} else {
			_, err = s.d.Instances.SetVerification(ctx, tx, id, v.v)
		}
		return err
	})
	if err == nil {
		s.countCheck(v.v)
	}
	return v.v, err
}

// countCheck counts a verification that reached its verdict (connector_check).
func (s *Service) countCheck(v domain.Verification) {
	outcome := "ok"
	if v.Error != nil {
		outcome = v.Error.Code
	}
	analytics.Count(s.d.Counter, "connector_check", map[string]string{"kind": "mcp", "outcome": outcome})
}

type probed struct {
	v domain.Verification
	d *discovery
}

// probeRow lists the tools until it succeeds, fails for good, or the safety
// deadline passes.
func (s *Service) probeRow(ctx context.Context, inst domain.Instance, merged map[string]any, extra http.Header) probed {
	fail := func(code, msg string, detail any) probed {
		return probed{v: s.payload(domain.VerifyFailed, failure(code, msg, detail))}
	}
	t, err := s.targetOf(inst, merged)
	if err != nil {
		return fail(CodeMCPError, err.Error(), nil)
	}
	h := http.Header{}
	for k, v := range plainHeaders(merged) {
		h.Set(k, v)
	}
	for k, vs := range extra {
		h[k] = vs
	}
	key := mcpclient.VerdictKey(inst.ID, merged)
	deadline := time.Now().Add(verifySafetyDeadline)
	var last error
	for {
		d, err := s.listOnce(ctx, t, h, key)
		if err == nil {
			s.d.Log.Info("verify: succeeded", "instance_id", inst.ID, "type", inst.Transport, "tools_count", len(d.tools))
			return probed{v: s.payload(domain.VerifySucceeded, nil), d: d}
		}
		if mcpclient.IsTransient(err) {
			last = err
			if time.Now().Add(listRetryDelay).After(deadline) {
				break
			}
			select {
			case <-ctx.Done():
				return fail(CodeMCPError, ctx.Err().Error(), nil)
			case <-time.After(listRetryDelay):
			}
			continue
		}
		var un *mcpclient.UnauthorizedError
		if errors.As(err, &un) {
			sent := inst.AuthConfigID != nil || len(inst.EnvVars()) > 0 || len(extra) > 0
			refusal := un.Refusal()
			if !sent && !un.InsufficientScope {
				refusal = "requires sign-in or a key"
			}
			s.d.Log.Warn("verify: upstream refused the credentials", "instance_id", inst.ID, "status", un.Status)
			return fail(CodeUpstreamUnauthorized, fmt.Sprintf("%s %s (HTTP %d)", inst.Name, refusal, un.Status), un.Data())
		}
		msg := errorMessage(err)
		var detail any
		var start *mcpclient.StartupFailureError
		if domain.IsContainer(inst.Transport) && errors.As(err, &start) {
			detail = start.Detail
		}
		var rpc *mcpclient.RPCError
		if inst.Transport == domain.TransportURL && !errors.As(err, &rpc) {
			s.d.Log.Warn("verify: could not connect to url endpoint", "instance_id", inst.ID, "error", err)
			msg = urlConnectFailed
		}
		s.d.Log.Warn("verify: mcp protocol error", "instance_id", inst.ID, "error", err)
		return fail(CodeMCPError, msg, detail)
	}
	msg := fmt.Sprintf("MCP did not become ready within %ds: %v", int(verifySafetyDeadline/time.Second), last)
	if inst.Transport == domain.TransportURL {
		s.d.Log.Warn("verify: url endpoint never answered", "instance_id", inst.ID, "error", msg)
		msg = urlConnectFailed
	}
	return fail(CodeListToolsTimeout, msg, nil)
}

// errorMessage names the failure's kind as Python's "{type}: {message}" did.
func errorMessage(err error) string {
	var rpc *mcpclient.RPCError
	var start *mcpclient.StartupFailureError
	switch {
	case errors.As(err, &rpc):
		return "MCPError: " + rpc.Message
	case errors.As(err, &start):
		return "MCPGatewayStartupFailureError: " + start.Error()
	}
	return err.Error()
}

// eraVerdicts is the process's verdict cache.
//
//nolint:gochecknoglobals // a process cache, like the Python module-level one; it outlives a Service rebuilt by Use
var eraVerdicts = mcpclient.NewVerdicts(eraVerdictTTL)

// listOnce is one attempt: connect, list tools and, when the server offers
// the events extension, its event types.
func (s *Service) listOnce(ctx context.Context, t target, h http.Header, key string) (*discovery, error) {
	ctx, cancel := context.WithTimeout(ctx, listAttemptTimeout)
	defer cancel()
	c, err := mcpclient.Connect(ctx, mcpclient.Options{URL: t.url, Transport: t.declared, RoundTripper: t.transport,
		Headers: h, Verdicts: eraVerdicts, VerdictKey: key})
	if err != nil {
		return nil, err
	}
	defer c.Close()
	listed, err := c.ListTools(ctx)
	if err != nil {
		return nil, err
	}
	tools := make([]any, 0, len(listed))
	for _, tool := range listed {
		tools = append(tools, mcpclient.SerializeTool(tool))
	}
	d := &discovery{tools: tools}
	ext, _ := c.ServerCapabilities()["extensions"].(map[string]any)
	settings, ok := ext[eventsExtension].(map[string]any)
	if !ok {
		return d, nil
	}
	record := map[string]any{"extension": eventsExtension, "settings": settings,
		"protocol_version": c.ProtocolVersion(), "events": []any{}}
	types, err := listEventTypes(ctx, c)
	if err != nil {
		var rpc *mcpclient.RPCError
		if !errors.As(err, &rpc) && !errors.Is(err, errEventList) {
			return nil, err
		}
		s.d.Log.Warn("verify: events/list failed", "error", err)
		record["error"] = err.Error()
	} else {
		record["events"] = types
	}
	record["listed_at"] = s.d.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00")
	d.events = record
	return d, nil
}

var errEventList = errors.New("events/list")

// listEventTypes is every event type events/list returns, page by page.
func listEventTypes(ctx context.Context, c *mcpclient.Client) ([]any, error) {
	var listed []any
	cursor := ""
	seen := map[string]bool{}
	for range maxEventPages {
		var params map[string]any
		if cursor != "" {
			params = map[string]any{"cursor": cursor}
		}
		raw, err := c.Request(ctx, "events/list", params)
		if err != nil {
			return nil, err
		}
		var page struct {
			Events     []any  `json:"events"`
			NextCursor string `json:"nextCursor"`
		}
		if err := json.Unmarshal(raw, &page); err != nil {
			return nil, fmt.Errorf("%w: %w", errEventList, err)
		}
		for _, e := range page.Events {
			if m, ok := e.(map[string]any); ok {
				if _, ok := m["name"].(string); ok {
					listed = append(listed, m)
				}
			}
		}
		if page.NextCursor == "" {
			if len(listed) > maxEventTypes {
				listed = listed[:maxEventTypes]
			}
			if listed == nil {
				listed = []any{}
			}
			return listed, nil
		}
		if seen[page.NextCursor] {
			return nil, fmt.Errorf("%w: cursor %q repeats", errEventList, page.NextCursor)
		}
		seen[page.NextCursor] = true
		cursor = page.NextCursor
	}
	return nil, fmt.Errorf("%w: more than %d pages", errEventList, maxEventPages)
}

// DiscoverTools is discover_and_store_tools: a verification, then the tools it stored.
func (s *Service) DiscoverInstanceTools(ctx context.Context, ws scope.Workspace, id uuid.UUID) ([]any, domain.Verification, error) {
	v, err := s.Verify(ctx, ws, id, true)
	if err != nil {
		return nil, v, err
	}
	inst, err := s.instanceIn(ctx, ws, id)
	if err != nil {
		return nil, v, err
	}
	tools := inst.Tools
	if tools == nil {
		tools = []any{}
	}
	return tools, v, nil
}

// VerifyInBackground starts a verification detached from the request (the
// create of a container instance); a process that dies leaves never_attempted
// or a stale in_progress for the monitor.
func (s *Service) VerifyInBackground(ws scope.Workspace, id uuid.UUID) {
	go func() {
		ctx := context.Background()
		inst, err := s.instanceIn(ctx, ws, id)
		if err == nil {
			_, err = s.verifyInstance(ctx, ws, inst, false)
		}
		if err != nil {
			s.d.Log.Error("background verification failed", "instance_id", id, "error", err)
		}
	}()
}
