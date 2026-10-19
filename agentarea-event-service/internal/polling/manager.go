// Package polling runs one poller per poll source and keeps the sources that
// register a webhook registered (ADR-0040 §3). The set of sources is read
// again every reconcile interval; a poller whose source changed is replaced.
package polling

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"reflect"
	"sync"
	"time"

	"go.opentelemetry.io/otel/trace"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/claim"
	"github.com/agentarea/event-service/internal/mcpevents"
	"github.com/agentarea/event-service/internal/secrets"
	"github.com/agentarea/event-service/internal/source"
	"github.com/agentarea/event-service/internal/template"
	"github.com/agentarea/event-service/internal/tracing"
	"github.com/agentarea/event-service/internal/transport"
)

// Sources reads the sources and records what polling and registration did.
type Sources interface {
	Load(ctx context.Context) ([]source.Source, error)
	Polled(ctx context.Context, sourceID, cursor string) error
	Failed(ctx context.Context, sourceID, reason string) error
	Registered(ctx context.Context, sourceID, url string) error
	SubscribeFailed(ctx context.Context, sourceID, reason string, retryIn time.Duration) error
	Subscribed(ctx context.Context, sourceID, url, subscriptionID string, refreshBefore *time.Time, cursor string) error
}

// MCPEvents subscribes an mcp_events webhook source at its MCP server and
// takes the subscription back, through the mcp-manager gateway.
type MCPEvents interface {
	Subscribe(ctx context.Context, instanceID string, req mcpevents.SubscribeRequest) (mcpevents.SubscribeResult, error)
	Unsubscribe(ctx context.Context, instanceID string, req mcpevents.UnsubscribeRequest) error
}

// mcpSubscriptionTTL is the lifetime asked for; the server's grant decides.
const mcpSubscriptionTTL = time.Hour

// maxSubscribeBackoff caps the wait between failed subscription attempts.
const maxSubscribeBackoff = time.Hour

// Publisher hands raw items to the platform's ingest.
type Publisher interface {
	Item(ctx context.Context, sourceID string, item any) error
	Gap(ctx context.Context, sourceID, reason string) error
}

// Caller sends a templated request to a provider.
type Caller interface {
	Call(ctx context.Context, req catalog.Request, v template.Values) ([]byte, error)
}

// Claimer lets one replica at a time act for a source.
type Claimer interface {
	TryClaim(ctx context.Context, id string) (bool, error)
	Renew(ctx context.Context, id string) error
	Release(ctx context.Context, id string) error
}

// Manager owns the pollers and the registrations.
type Manager struct {
	sources    Sources
	secrets    secrets.Reader
	transports transport.Set
	publisher  Publisher
	caller     Caller
	mcp        MCPEvents
	claimer    Claimer
	apiURL     string
	interval   time.Duration
	maxPollers int

	mu      sync.Mutex
	pollers map[string]*runningPoller
	// registered remembers how each source this replica registered was
	// registered, so a deleted source can still be unregistered.
	registered map[string]registration
}

type registration struct {
	request catalog.Request
	values  template.Values
	// mcp, when set, is an MCP Events subscription, taken back by its key.
	mcp *mcpRegistration
}

type mcpRegistration struct {
	instanceID string
	key        mcpevents.UnsubscribeRequest
}

// Deps are what a Manager runs on.
type Deps struct {
	Sources    Sources
	Secrets    secrets.Reader
	Transports transport.Set
	Publisher  Publisher
	Caller     Caller
	MCP        MCPEvents
	Claimer    Claimer
	// APIURL is the public base of /webhooks/{webhook_id}.
	APIURL string
	// Interval is how often the set of sources is read again.
	Interval   time.Duration
	MaxPollers int
}

// NewManager builds a Manager.
func NewManager(d Deps) *Manager {
	return &Manager{
		sources:    d.Sources,
		secrets:    d.Secrets,
		transports: d.Transports,
		publisher:  d.Publisher,
		caller:     d.Caller,
		mcp:        d.MCP,
		claimer:    d.Claimer,
		apiURL:     d.APIURL,
		interval:   d.Interval,
		maxPollers: d.MaxPollers,
		pollers:    make(map[string]*runningPoller),
		registered: make(map[string]registration),
	}
}

// Run reconciles until ctx is cancelled.
func (m *Manager) Run(ctx context.Context) error {
	slog.Info("polling manager started", "interval", m.interval)
	ticker := time.NewTicker(m.interval)
	defer ticker.Stop()

	m.reconcile(ctx)
	for {
		select {
		case <-ctx.Done():
			m.stopAll()
			return ctx.Err()
		case <-ticker.C:
			m.reconcile(ctx)
		}
	}
}

func (m *Manager) reconcile(ctx context.Context) {
	sources, err := m.sources.Load(ctx)
	if err != nil {
		slog.Error("failed to load stream sources", "error", err)
		return
	}
	present := make(map[string]bool, len(sources))
	var polled []source.Source
	for _, src := range sources {
		present[src.ID] = true
		switch src.Kind {
		case source.KindWebhook:
			if src.Entry.Registration != nil && src.Entry.Registration.Transport == transport.MCPEvents {
				m.subscribe(ctx, src)
				continue
			}
			m.register(ctx, src)
		case source.KindPoll:
			polled = append(polled, src)
		}
	}
	m.unregisterGone(ctx, present)
	m.reconcilePollers(ctx, polled)
}

func (m *Manager) values(ctx context.Context, src source.Source) (template.Values, error) {
	creds, err := secrets.Credentials(ctx, m.secrets, src.WorkspaceID, src.Slug, src.CredentialKey)
	if err != nil {
		return template.Values{}, err
	}
	return template.Values{
		Credentials: creds,
		Config:      src.Config,
		Cursor:      src.Cursor,
		WebhookURL:  src.WebhookURL(m.apiURL),
		SourceID:    src.ID,
	}, nil
}

// register points the provider at a webhook source's URL unless the URL it
// last registered is that one already. Calls are idempotent at the provider,
// so a repeat after a crash between the call and the record is harmless.
func (m *Manager) register(ctx context.Context, src source.Source) {
	if src.Entry.Registration == nil || src.Entry.Registration.Register == nil {
		return
	}
	url := src.WebhookURL(m.apiURL)
	if url == "" || src.RegisteredURL == url {
		m.remember(ctx, src)
		return
	}
	claimID := "register:" + src.ID
	claimed, err := m.claimer.TryClaim(ctx, claimID)
	if err != nil || !claimed {
		return
	}
	defer func() {
		if err := m.claimer.Release(context.Background(), claimID); err != nil {
			slog.Warn("failed to release registration claim", "source_id", src.ID, "error", err)
		}
	}()

	values, err := m.values(ctx, src)
	if err == nil {
		_, err = m.caller.Call(ctx, *src.Entry.Registration.Register, values)
	}
	if err != nil {
		slog.Warn("webhook registration failed", "source_id", src.ID, "slug", src.Slug, "error", err)
		m.record(ctx, m.sources.Failed(ctx, src.ID, "registration: "+err.Error()))
		return
	}
	if err := m.sources.Registered(ctx, src.ID, url); err != nil {
		slog.Error("failed to record webhook registration", "source_id", src.ID, "error", err)
		return
	}
	slog.Info("webhook registered", "source_id", src.ID, "slug", src.Slug)
	m.rememberValues(src, values)
}

// subscribe makes or refreshes an mcp_events source's subscription at its MCP
// server: when it has none at the source's URL, or its grant runs out within
// the refresh margin. The server sends the verification challenge to the
// source's URL while it answers, so the source's credentials exist already.
// A failed attempt is tried again after a backoff, not every round.
func (m *Manager) subscribe(ctx context.Context, src source.Source) {
	url := src.WebhookURL(m.apiURL)
	if url == "" {
		return
	}
	if !m.subscriptionDue(src, url) {
		m.rememberSubscription(src, url)
		return
	}
	if src.MCPInstanceID == "" {
		m.subscribeFailed(ctx, src, "subscription: the source names no MCP server of its workspace")
		return
	}
	cfg, err := transport.ReadMCPEventsConfig(src.Config)
	if err != nil {
		m.subscribeFailed(ctx, src, "subscription: "+err.Error())
		return
	}
	key := mcpEventsKey(cfg, url)
	claimID := "register:" + src.ID
	claimed, err := m.claimer.TryClaim(ctx, claimID)
	if err != nil || !claimed {
		return
	}
	defer func() {
		if err := m.claimer.Release(context.Background(), claimID); err != nil {
			slog.Warn("failed to release subscription claim", "source_id", src.ID, "error", err)
		}
	}()

	values, err := m.values(ctx, src)
	if err != nil {
		m.subscribeFailed(ctx, src, "subscription: "+err.Error())
		return
	}
	secret := values.Credentials["signing_secret"]
	if secret == "" {
		m.subscribeFailed(ctx, src, "subscription: the source has no signing_secret")
		return
	}
	var cursor *string
	if src.Cursor != "" {
		stored := src.Cursor
		cursor = &stored
	}
	grant, err := m.mcp.Subscribe(ctx, src.MCPInstanceID, mcpevents.SubscribeRequest{
		Name: cfg.Event, Arguments: cfg.Arguments,
		Delivery: mcpevents.Delivery{URL: url, Secret: secret},
		Cursor:   cursor, TTLMs: mcpSubscriptionTTL.Milliseconds(),
	})
	if err != nil {
		m.subscribeFailed(ctx, src, "subscription: "+err.Error())
		return
	}
	watermark := ""
	if grant.Cursor != nil {
		watermark = *grant.Cursor
	}
	if err := m.sources.Subscribed(ctx, src.ID, url, grant.ID, grant.RefreshBefore, watermark); err != nil {
		slog.Error("failed to record MCP Events subscription", "source_id", src.ID, "error", err)
		return
	}
	if grant.Truncated && cursor != nil {
		if err := m.publisher.Gap(ctx, src.ID, "the MCP server resumed delivery after the stored cursor (truncated)"); err != nil {
			slog.Error("failed to publish a subscription gap", "source_id", src.ID, "error", err)
		}
	}
	slog.Info("MCP Events subscription granted", "source_id", src.ID, "subscription_id", grant.ID, "refresh_before", grant.RefreshBefore)
	m.rememberMCP(src.ID, src.MCPInstanceID, key)
}

// subscriptionDue reports whether the source has no live subscription at url
// or its grant ends within the refresh margin; a grant with no expiry is due
// only when it is missing. After a failed attempt it is due at the retry time.
func (m *Manager) subscriptionDue(src source.Source, url string) bool {
	if src.PollError != "" {
		return src.RefreshBefore == nil || !time.Now().Before(*src.RefreshBefore)
	}
	if src.RegisteredURL != url || src.SubscriptionID == "" {
		return true
	}
	if src.RefreshBefore == nil {
		return false
	}
	return time.Until(*src.RefreshBefore) < m.refreshMargin()
}

// subscribeFailed records why subscribing failed and when to try again.
func (m *Manager) subscribeFailed(ctx context.Context, src source.Source, reason string) {
	retryIn := m.subscribeBackoff(src)
	slog.Warn("MCP Events subscription failed", "source_id", src.ID, "reason", reason, "retry_in", retryIn)
	m.record(ctx, m.sources.SubscribeFailed(ctx, src.ID, reason, retryIn))
}

// subscribeBackoff starts at the reconcile interval and doubles the wait the
// last failed attempt was given, up to maxSubscribeBackoff.
func (m *Manager) subscribeBackoff(src source.Source) time.Duration {
	if src.PollError == "" || src.RefreshBefore == nil || src.PolledAt == nil {
		return min(m.interval, maxSubscribeBackoff)
	}
	return min(max(m.interval, 2*src.RefreshBefore.Sub(*src.PolledAt)), maxSubscribeBackoff)
}

// rememberSubscription keeps what taking back a live subscription takes.
func (m *Manager) rememberSubscription(src source.Source, url string) {
	if src.SubscriptionID == "" || src.MCPInstanceID == "" {
		return
	}
	cfg, err := transport.ReadMCPEventsConfig(src.Config)
	if err != nil {
		return
	}
	m.rememberMCP(src.ID, src.MCPInstanceID, mcpEventsKey(cfg, url))
}

func mcpEventsKey(cfg transport.MCPEventsConfig, url string) mcpevents.UnsubscribeRequest {
	return mcpevents.UnsubscribeRequest{Name: cfg.Event, Arguments: cfg.Arguments, Delivery: mcpevents.Delivery{URL: url}}
}

// refreshMargin leaves at least three reconcile rounds to refresh in.
func (m *Manager) refreshMargin() time.Duration {
	return max(time.Minute, 3*m.interval)
}

func (m *Manager) rememberMCP(sourceID, instanceID string, key mcpevents.UnsubscribeRequest) {
	m.mu.Lock()
	m.registered[sourceID] = registration{mcp: &mcpRegistration{instanceID: instanceID, key: key}}
	m.mu.Unlock()
}

// remember keeps what unregistering a registered source takes.
func (m *Manager) remember(ctx context.Context, src source.Source) {
	if src.RegisteredURL == "" || src.Entry.Registration.Unregister == nil {
		return
	}
	m.mu.Lock()
	_, known := m.registered[src.ID]
	m.mu.Unlock()
	if known {
		return
	}
	values, err := m.values(ctx, src)
	if err != nil {
		slog.Warn("cannot read the credentials of a registered source", "source_id", src.ID, "error", err)
		return
	}
	m.rememberValues(src, values)
}

func (m *Manager) rememberValues(src source.Source, values template.Values) {
	if src.Entry.Registration.Unregister == nil {
		return
	}
	m.mu.Lock()
	m.registered[src.ID] = registration{request: *src.Entry.Registration.Unregister, values: values}
	m.mu.Unlock()
}

// unregisterGone takes back the webhook of every remembered source that no
// longer exists.
func (m *Manager) unregisterGone(ctx context.Context, present map[string]bool) {
	m.mu.Lock()
	gone := make(map[string]registration)
	for id, reg := range m.registered {
		if !present[id] {
			gone[id] = reg
			delete(m.registered, id)
		}
	}
	m.mu.Unlock()
	for id, reg := range gone {
		if reg.mcp != nil {
			m.unsubscribe(ctx, id, reg.mcp)
			continue
		}
		if _, err := m.caller.Call(ctx, reg.request, reg.values); err != nil {
			slog.Warn("webhook of a deleted source could not be unregistered", "source_id", id, "error", err)
			continue
		}
		slog.Info("webhook of a deleted source unregistered", "source_id", id)
	}
}

// unsubscribe takes back the subscription of a deleted mcp_events source; one
// the server no longer knows is gone already.
func (m *Manager) unsubscribe(ctx context.Context, id string, reg *mcpRegistration) {
	err := m.mcp.Unsubscribe(ctx, reg.instanceID, reg.key)
	var rpc *mcpevents.RPCError
	if errors.As(err, &rpc) && rpc.Code == mcpevents.CodeNotFound {
		err = nil
	}
	if err != nil {
		slog.Warn("MCP Events subscription of a deleted source could not be taken back", "source_id", id, "error", err)
		return
	}
	slog.Info("MCP Events subscription of a deleted source taken back", "source_id", id)
}

func (m *Manager) record(_ context.Context, err error) {
	if err != nil {
		slog.Error("failed to record source state", "error", err)
	}
}

// runningPoller is a poller goroutine and the source it was started with.
type runningPoller struct {
	cancel context.CancelFunc
	src    source.Source
	done   chan struct{}
}

// serves reports whether the poller still matches the source: a changed entry,
// config or credential key needs a new poller.
func (p *runningPoller) serves(src source.Source) bool {
	return p.src.EntrySpec == src.EntrySpec && p.src.CredentialKey == src.CredentialKey &&
		reflect.DeepEqual(p.src.Config, src.Config)
}

func (m *Manager) reconcilePollers(ctx context.Context, sources []source.Source) {
	m.mu.Lock()
	defer m.mu.Unlock()

	desired := make(map[string]source.Source, len(sources))
	for _, src := range sources {
		desired[src.ID] = src
	}
	replaced := make(map[string]<-chan struct{})
	for id, p := range m.pollers {
		src, ok := desired[id]
		if ok && p.serves(src) {
			continue
		}
		if ok {
			slog.Info("restarting poller for a changed source", "source_id", id)
			replaced[id] = p.done
		} else {
			slog.Info("stopping poller for a removed source", "source_id", id)
		}
		p.cancel()
		delete(m.pollers, id)
	}
	for id, src := range desired {
		if _, running := m.pollers[id]; running {
			continue
		}
		if len(m.pollers) >= m.maxPollers {
			slog.Warn("max pollers reached, skipping source", "source_id", id, "max", m.maxPollers)
			continue
		}
		m.startPoller(ctx, src, replaced[id])
	}
}

// startPoller launches the goroutine of one source. It waits for the poller it
// replaces to release its claim first. Must be called with m.mu held.
func (m *Manager) startPoller(ctx context.Context, src source.Source, previous <-chan struct{}) {
	pollerCtx, cancel := context.WithCancel(ctx)
	running := &runningPoller{cancel: cancel, src: src, done: make(chan struct{})}
	m.pollers[src.ID] = running

	go func() {
		defer func() {
			cancel()
			m.mu.Lock()
			if m.pollers[src.ID] == running {
				delete(m.pollers, src.ID)
			}
			m.mu.Unlock()
			close(running.done)
			slog.Info("poller stopped", "source_id", src.ID)
		}()
		if previous != nil {
			select {
			case <-previous:
			case <-pollerCtx.Done():
				return
			}
		}
		claimed, err := m.claimer.TryClaim(pollerCtx, src.ID)
		if err != nil {
			slog.Error("failed to claim source", "source_id", src.ID, "error", err)
			return
		}
		if !claimed {
			slog.Debug("source polled by another replica", "source_id", src.ID)
			return
		}
		defer func() {
			if err := m.claimer.Release(context.Background(), src.ID); err != nil {
				slog.Warn("failed to release claim", "source_id", src.ID, "error", err)
			}
		}()
		go m.renew(pollerCtx, cancel, src.ID)

		slog.Info("starting poller", "source_id", src.ID, "slug", src.Slug, "transport", src.Entry.Poll.Transport)
		m.runPoller(pollerCtx, src)
	}()
}

func (m *Manager) renew(ctx context.Context, cancel context.CancelFunc, id string) {
	ticker := time.NewTicker(20 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			err := m.claimer.Renew(ctx, id)
			if errors.Is(err, claim.ErrClaimLost) {
				// Another replica may poll it now; stop rather than publish twice.
				slog.Warn("claim lost, stopping poller", "source_id", id, "error", err)
				cancel()
				return
			}
			if err != nil {
				slog.Warn("failed to renew claim", "source_id", id, "error", err)
			}
		}
	}
}

// runPoller polls one source until ctx ends. A poll publishes every item in
// order, then stores the cursor: a crash between the two publishes the items
// again, and the event key dedups them.
func (m *Manager) runPoller(ctx context.Context, src source.Source) {
	if src.Entry.Poll == nil {
		m.record(ctx, m.sources.Failed(ctx, src.ID, "the source type has no poll block"))
		return
	}
	interval, err := src.Entry.Poll.PollInterval()
	if err != nil {
		m.record(ctx, m.sources.Failed(ctx, src.ID, err.Error()))
		return
	}
	tr, err := m.transports.Get(src.Entry.Poll.Transport)
	if err != nil {
		m.record(ctx, m.sources.Failed(ctx, src.ID, err.Error()))
		return
	}
	m.clearWebhook(ctx, src)

	cursor := src.Cursor
	first := true
	wait := interval
	RunLoop(ctx, src.ID, func(ctx context.Context) error {
		if !first && wait > 0 {
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(wait):
			}
		}
		first = false
		next, asked, err := m.pollOnce(ctx, src, tr, cursor)
		if err != nil {
			if ctx.Err() == nil {
				m.record(ctx, m.sources.Failed(ctx, src.ID, err.Error()))
			}
			return err
		}
		cursor = next
		wait = interval
		if asked > 0 {
			wait = asked
		}
		return nil
	})
}

// clearWebhook takes back a webhook registered for the source's provider
// account before polling it: a provider that registers webhooks holds the
// updates for the webhook and refuses a poll while one is set.
func (m *Manager) clearWebhook(ctx context.Context, src source.Source) {
	if src.Entry.Registration == nil || src.Entry.Registration.Unregister == nil {
		return
	}
	values, err := m.values(ctx, src)
	if err == nil {
		_, err = m.caller.Call(ctx, *src.Entry.Registration.Unregister, values)
	}
	if err != nil {
		slog.Warn("could not clear the provider webhook before polling", "source_id", src.ID, "error", err)
	}
}

// pollOnce returns the cursor to poll from next and the wait the source asked
// for (0: the entry's interval).
func (m *Manager) pollOnce(ctx context.Context, src source.Source, tr transport.Transport, cursor string) (next string, wait time.Duration, err error) {
	ctx, span := tracing.Tracer().Start(ctx, "poll "+src.Entry.Poll.Transport, trace.WithAttributes(
		tracing.AttrSourceID.String(src.ID),
		tracing.AttrSourceTransport.String(src.Entry.Poll.Transport),
	))
	defer func() {
		if err != nil {
			tracing.RecordError(span, err)
		}
		span.End()
	}()

	values, err := m.values(ctx, src)
	if err != nil {
		return cursor, 0, fmt.Errorf("credentials: %w", err)
	}
	values.Cursor = cursor
	result, err := tr.Fetch(ctx, transport.Fetch{
		SourceID: src.ID, Poll: *src.Entry.Poll, Values: values, MCPInstanceID: src.MCPInstanceID,
	})
	if err != nil {
		return cursor, 0, err
	}
	span.SetAttributes(tracing.AttrItemsFetched.Int(len(result.Items)))

	if result.Gap != "" {
		if err := m.publisher.Gap(ctx, src.ID, result.Gap); err != nil {
			return cursor, 0, err
		}
	}
	for _, item := range result.Items {
		if err := m.publisher.Item(ctx, src.ID, item); err != nil {
			return cursor, 0, err
		}
	}
	if result.Cursor != "" {
		cursor = result.Cursor
	}
	if err := m.sources.Polled(ctx, src.ID, result.Cursor); err != nil {
		// The items are out; the next poll repeats them and ingest dedups.
		return cursor, 0, err
	}
	if len(result.Items) > 0 {
		slog.Info("published poll items", "source_id", src.ID, "items", len(result.Items))
	}
	return cursor, result.Next, nil
}

func (m *Manager) stopAll() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for id, p := range m.pollers {
		slog.Info("stopping poller on shutdown", "source_id", id)
		p.cancel()
	}
	m.pollers = make(map[string]*runningPoller)
}
