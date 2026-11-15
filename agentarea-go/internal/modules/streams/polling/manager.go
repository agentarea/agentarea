// Package polling runs one poller per poll source and keeps the sources that
// register a webhook registered (ADR-0040 §3), the event service folded into
// streams. The set of sources is read again every reconcile interval; a poller
// whose source changed is replaced. A polled item goes through the source's
// ingest in-process, the path a webhook request takes.
package polling

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"reflect"
	"sync"
	"sync/atomic"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"

	kobs "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// mcpSubscriptionTTL is the lifetime asked for; the server's grant decides.
const mcpSubscriptionTTL = time.Hour

// maxSubscribeBackoff caps the wait between failed subscription attempts.
const maxSubscribeBackoff = time.Hour

// Manager owns the pollers and the registrations.
type Manager struct {
	sources     Sources
	credentials Credentials
	intake      Intake
	transports  Transports
	caller      RequestCaller
	mcp         MCPSubscriber
	claimer     Claimer
	webhookURL  func(string) string
	interval    time.Duration
	maxPollers  int
	now         func() time.Time
	log         *slog.Logger

	metrics pollMetrics

	mu      sync.Mutex
	pollers map[string]*runningPoller
	// overCapacity counts the poll sources left without a poller because
	// maxPollers was reached.
	overCapacity int
	// registered remembers how each source this replica registered was
	// registered, so a deleted source can still be unregistered.
	registered map[string]registration
}

type registration struct {
	request Request
	values  Values
	// mcp, when set, is an MCP Events subscription, taken back by its key.
	mcp *mcpRegistration
}

type mcpRegistration struct {
	instanceID string
	key        UnsubscribeRequest
}

// NewManager builds a Manager.
func NewManager(d Deps) *Manager {
	m := &Manager{
		sources: d.Sources, credentials: d.Credentials, intake: d.Intake, transports: d.Transports,
		caller: d.Caller, mcp: d.MCP, claimer: d.Claimer, webhookURL: d.WebhookURL,
		interval: d.Interval, maxPollers: d.MaxPollers, now: d.Now, log: d.Log,
		pollers:    make(map[string]*runningPoller),
		registered: make(map[string]registration),
	}
	if m.now == nil {
		m.now = time.Now
	}
	if m.log == nil {
		m.log = slog.Default()
	}
	m.metrics = newPollMetrics(m)
	return m
}

// Run reconciles until ctx is cancelled.
func (m *Manager) Run(ctx context.Context) error {
	m.log.InfoContext(ctx, "polling manager started", "interval", m.interval)
	ticker := time.NewTicker(m.interval)
	defer ticker.Stop()

	m.reconcile(ctx)
	for {
		select {
		case <-ctx.Done():
			m.stopAll(context.WithoutCancel(ctx))
			return ctx.Err()
		case <-ticker.C:
			m.reconcile(ctx)
		}
	}
}

func (m *Manager) reconcile(ctx context.Context) {
	sources, err := m.sources.Load(ctx)
	if err != nil {
		m.log.ErrorContext(ctx, "failed to load stream sources", "error", err)
		return
	}
	present := make(map[string]bool, len(sources))
	var polled []Source
	for _, src := range sources {
		present[src.ID] = true
		switch src.Kind {
		case KindWebhook:
			if src.Entry.Registration != nil && src.Entry.Registration.Transport == MCPEvents {
				m.subscribe(ctx, src)
				continue
			}
			m.register(ctx, src)
		case KindPoll:
			polled = append(polled, src)
		}
	}
	m.unregisterGone(ctx, present)
	m.reconcilePollers(ctx, polled)
}

func (m *Manager) values(ctx context.Context, src Source) (Values, error) {
	creds := map[string]string{}
	if src.CredentialKey != "" {
		ws, err := scope.NewWorkspace(src.WorkspaceID, "")
		if err != nil {
			return Values{}, err
		}
		if creds, err = m.credentials(ctx, ws, src.CreatedBy, src.Slug, src.CredentialKey); err != nil {
			return Values{}, err
		}
	}
	return Values{
		Credentials: creds,
		Config:      src.Config,
		Cursor:      src.Cursor,
		WebhookURL:  m.urlOf(src),
		SourceID:    src.ID,
	}, nil
}

// urlOf is where the provider sends a webhook source's events; "" for a poll source.
func (m *Manager) urlOf(src Source) string {
	if src.WebhookID == "" {
		return ""
	}
	return m.webhookURL(src.WebhookID)
}

// register points the provider at a webhook source's URL unless the URL it
// last registered is that one already. Calls are idempotent at the provider,
// so a repeat after a crash between the call and the record is harmless.
func (m *Manager) register(ctx context.Context, src Source) {
	if src.Entry.Registration == nil || src.Entry.Registration.Register == nil {
		return
	}
	url := m.urlOf(src)
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
			m.log.WarnContext(ctx, "failed to release registration claim", "source_id", src.ID, "error", err)
		}
	}()

	values, err := m.values(ctx, src)
	if err == nil {
		_, err = m.caller.Call(ctx, *src.Entry.Registration.Register, values)
	}
	if err != nil {
		m.log.WarnContext(ctx, "webhook registration failed", "source_id", src.ID, "slug", src.Slug, "error", err)
		m.record(ctx, m.sources.Failed(ctx, src.ID, "registration: "+err.Error()))
		return
	}
	if err := m.sources.Registered(ctx, src.ID, url); err != nil {
		m.log.ErrorContext(ctx, "failed to record webhook registration", "source_id", src.ID, "error", err)
		return
	}
	m.log.InfoContext(ctx, "webhook registered", "source_id", src.ID, "slug", src.Slug)
	m.rememberValues(src, values)
}

// subscribe makes or refreshes an mcp_events source's subscription at its MCP
// server: when it has none at the source's URL, or its grant runs out within
// the refresh margin. The server sends the verification challenge to the
// source's URL while it answers, so the source's credentials exist already.
// A failed attempt is tried again after a backoff, not every round.
func (m *Manager) subscribe(ctx context.Context, src Source) {
	url := m.urlOf(src)
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
	cfg, err := ReadMCPEventsConfig(src.Config)
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
			m.log.WarnContext(ctx, "failed to release subscription claim", "source_id", src.ID, "error", err)
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
	grant, err := m.mcp.Subscribe(ctx, src.MCPInstanceID, SubscribeRequest{
		Name: cfg.Event, Arguments: cfg.Arguments,
		Delivery: Delivery{URL: url, Secret: secret},
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
		m.log.ErrorContext(ctx, "failed to record MCP Events subscription", "source_id", src.ID, "error", err)
		return
	}
	if grant.Truncated && cursor != nil {
		if err := m.intake.IngestGap(ctx, src.ID, "the MCP server resumed delivery after the stored cursor (truncated)", m.now()); err != nil {
			m.log.ErrorContext(ctx, "failed to publish a subscription gap", "source_id", src.ID, "error", err)
		}
	}
	m.log.InfoContext(ctx, "MCP Events subscription granted", "source_id", src.ID, "subscription_id", grant.ID, "refresh_before", grant.RefreshBefore)
	m.rememberMCP(src.ID, src.MCPInstanceID, key)
}

// subscriptionDue reports whether the source has no live subscription at url
// or its grant ends within the refresh margin; a grant with no expiry is due
// only when it is missing. After a failed attempt it is due at the retry time.
func (m *Manager) subscriptionDue(src Source, url string) bool {
	if src.PollError != "" {
		return src.RefreshBefore == nil || !m.now().Before(*src.RefreshBefore)
	}
	if src.RegisteredURL != url || src.SubscriptionID == "" {
		return true
	}
	if src.RefreshBefore == nil {
		return false
	}
	return src.RefreshBefore.Sub(m.now()) < m.refreshMargin()
}

// subscribeFailed records why subscribing failed and when to try again.
func (m *Manager) subscribeFailed(ctx context.Context, src Source, reason string) {
	retryIn := m.subscribeBackoff(src)
	m.log.WarnContext(ctx, "MCP Events subscription failed", "source_id", src.ID, "reason", reason, "retry_in", retryIn)
	m.record(ctx, m.sources.SubscribeFailed(ctx, src.ID, reason, retryIn))
}

// subscribeBackoff starts at the reconcile interval and doubles the wait the
// last failed attempt was given, up to maxSubscribeBackoff.
func (m *Manager) subscribeBackoff(src Source) time.Duration {
	if src.PollError == "" || src.RefreshBefore == nil || src.PolledAt == nil {
		return min(m.interval, maxSubscribeBackoff)
	}
	return min(max(m.interval, 2*src.RefreshBefore.Sub(*src.PolledAt)), maxSubscribeBackoff)
}

// rememberSubscription keeps what taking back a live subscription takes.
func (m *Manager) rememberSubscription(src Source, url string) {
	if src.SubscriptionID == "" || src.MCPInstanceID == "" {
		return
	}
	cfg, err := ReadMCPEventsConfig(src.Config)
	if err != nil {
		return
	}
	m.rememberMCP(src.ID, src.MCPInstanceID, mcpEventsKey(cfg, url))
}

func mcpEventsKey(cfg MCPEventsConfig, url string) UnsubscribeRequest {
	return UnsubscribeRequest{Name: cfg.Event, Arguments: cfg.Arguments, Delivery: Delivery{URL: url}}
}

// refreshMargin leaves at least three reconcile rounds to refresh in.
func (m *Manager) refreshMargin() time.Duration {
	return max(time.Minute, 3*m.interval)
}

func (m *Manager) rememberMCP(sourceID, instanceID string, key UnsubscribeRequest) {
	m.mu.Lock()
	m.registered[sourceID] = registration{mcp: &mcpRegistration{instanceID: instanceID, key: key}}
	m.mu.Unlock()
}

// remember keeps what unregistering a registered source takes.
func (m *Manager) remember(ctx context.Context, src Source) {
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
		m.log.WarnContext(ctx, "cannot read the credentials of a registered source", "source_id", src.ID, "error", err)
		return
	}
	m.rememberValues(src, values)
}

func (m *Manager) rememberValues(src Source, values Values) {
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
			m.log.WarnContext(ctx, "webhook of a deleted source could not be unregistered", "source_id", id, "error", err)
			continue
		}
		m.log.InfoContext(ctx, "webhook of a deleted source unregistered", "source_id", id)
	}
}

// unsubscribe takes back the subscription of a deleted mcp_events source; one
// the server no longer knows is gone already.
func (m *Manager) unsubscribe(ctx context.Context, id string, reg *mcpRegistration) {
	err := m.mcp.Unsubscribe(ctx, reg.instanceID, reg.key)
	var rpc *RPCError
	if errors.As(err, &rpc) && rpc.Code == CodeNotFound {
		err = nil
	}
	if err != nil {
		m.log.WarnContext(ctx, "MCP Events subscription of a deleted source could not be taken back", "source_id", id, "error", err)
		return
	}
	m.log.InfoContext(ctx, "MCP Events subscription of a deleted source taken back", "source_id", id)
}

func (m *Manager) record(ctx context.Context, err error) {
	if err != nil {
		m.log.ErrorContext(ctx, "failed to record source state", "error", err)
	}
}

// runningPoller is a poller goroutine and the source it was started with.
type runningPoller struct {
	cancel context.CancelFunc
	src    Source
	done   chan struct{}
	// polling is set once the poller holds the source's claim.
	polling atomic.Bool
}

// serves reports whether the poller still matches the source: a changed entry,
// config or credential key needs a new poller.
func (p *runningPoller) serves(src Source) bool {
	return p.src.EntrySpec == src.EntrySpec && p.src.CredentialKey == src.CredentialKey &&
		reflect.DeepEqual(p.src.Config, src.Config)
}

func (m *Manager) reconcilePollers(ctx context.Context, sources []Source) {
	m.mu.Lock()
	defer m.mu.Unlock()

	desired := make(map[string]Source, len(sources))
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
			m.log.InfoContext(ctx, "restarting poller for a changed source", "source_id", id)
			replaced[id] = p.done
		} else {
			m.log.InfoContext(ctx, "stopping poller for a removed source", "source_id", id)
		}
		p.cancel()
		delete(m.pollers, id)
	}
	m.overCapacity = 0
	for id, src := range desired {
		if _, running := m.pollers[id]; running {
			continue
		}
		if len(m.pollers) >= m.maxPollers {
			m.log.WarnContext(ctx, "max pollers reached, skipping source", "source_id", id, "max", m.maxPollers)
			m.overCapacity++
			continue
		}
		m.startPoller(ctx, src, replaced[id])
	}
}

// startPoller launches the goroutine of one source. It waits for the poller it
// replaces to release its claim first. Must be called with m.mu held.
func (m *Manager) startPoller(ctx context.Context, src Source, previous <-chan struct{}) {
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
			m.log.InfoContext(ctx, "poller stopped", "source_id", src.ID)
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
			m.log.ErrorContext(ctx, "failed to claim source", "source_id", src.ID, "error", err)
			return
		}
		if !claimed {
			m.log.DebugContext(ctx, "source polled by another replica", "source_id", src.ID)
			return
		}
		defer func() {
			if err := m.claimer.Release(context.Background(), src.ID); err != nil {
				m.log.WarnContext(ctx, "failed to release claim", "source_id", src.ID, "error", err)
			}
		}()
		go m.renew(pollerCtx, cancel, src.ID)
		running.polling.Store(true)

		m.log.InfoContext(ctx, "starting poller", "source_id", src.ID, "slug", src.Slug, "transport", src.Entry.Poll.Transport)
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
			if errors.Is(err, ErrClaimLost) {
				// Another replica may poll it now; stop rather than publish twice.
				m.log.WarnContext(ctx, "claim lost, stopping poller", "source_id", id, "error", err)
				cancel()
				return
			}
			if err != nil {
				m.log.WarnContext(ctx, "failed to renew claim", "source_id", id, "error", err)
			}
		}
	}
}

// runPoller polls one source until ctx ends. A poll publishes every item in
// order, then stores the cursor: a crash between the two publishes the items
// again, and the event key dedups them.
func (m *Manager) runPoller(ctx context.Context, src Source) {
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
	RunLoop(ctx, m.log, src.ID, func(ctx context.Context) error {
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
func (m *Manager) clearWebhook(ctx context.Context, src Source) {
	if src.Entry.Registration == nil || src.Entry.Registration.Unregister == nil {
		return
	}
	values, err := m.values(ctx, src)
	if err == nil {
		_, err = m.caller.Call(ctx, *src.Entry.Registration.Unregister, values)
	}
	if err != nil {
		m.log.WarnContext(ctx, "could not clear the provider webhook before polling", "source_id", src.ID, "error", err)
	}
}

// pollOnce returns the cursor to poll from next and the wait the source asked
// for (0: the entry's interval).
func (m *Manager) pollOnce(ctx context.Context, src Source, tr Transport, cursor string) (next string, wait time.Duration, err error) {
	name := src.Entry.Poll.Transport
	ctx, span := otel.Tracer(kobs.MeterScope).Start(ctx, "poll "+name, trace.WithAttributes(
		attribute.String("agentarea.source.id", src.ID),
		attribute.String("agentarea.source.transport", name),
	))
	began, step := m.now(), stepCredentials
	defer func() {
		if err != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
		}
		span.End()
		m.metrics.poll(ctx, name, pollOutcome(step, err, ctx.Err() != nil), time.Since(began))
	}()

	values, err := m.values(ctx, src)
	if err != nil {
		return cursor, 0, fmt.Errorf("credentials: %w", err)
	}
	values.Cursor = cursor
	step = stepFetch
	result, err := tr.Fetch(ctx, Fetch{
		SourceID: src.ID, Poll: *src.Entry.Poll, Values: values, MCPInstanceID: src.MCPInstanceID,
	})
	if err != nil {
		return cursor, 0, err
	}
	span.SetAttributes(attribute.Int("agentarea.poll.items_fetched", len(result.Items)))

	step = stepPublish
	receivedAt := m.now()
	if result.Gap != "" {
		if err := m.intake.IngestGap(ctx, src.ID, result.Gap, receivedAt); err != nil {
			return cursor, 0, fmt.Errorf("gap: %w", err)
		}
		m.log.WarnContext(ctx, "source reported a gap", "source_id", src.ID, "reason", result.Gap)
	}
	for _, item := range result.Items {
		raw, err := json.Marshal(item)
		if err != nil {
			return cursor, 0, fmt.Errorf("encode item: %w", err)
		}
		if err := m.intake.IngestPolled(ctx, src.ID, raw, receivedAt); err != nil {
			if !errors.Is(err, ErrUnprocessable) {
				return cursor, 0, fmt.Errorf("ingest: %w", err)
			}
			m.log.ErrorContext(ctx, "polled item dropped: no retry can ingest it", "source_id", src.ID, "error", err)
			continue
		}
		m.metrics.itemPublished(ctx, name)
	}
	if result.Cursor != "" {
		cursor = result.Cursor
	}
	step = stepRecord
	if err := m.sources.Polled(ctx, src.ID, result.Cursor); err != nil {
		// The items are out; the next poll repeats them and ingest dedups.
		return cursor, 0, err
	}
	if len(result.Items) > 0 {
		m.log.InfoContext(ctx, "published poll items", "source_id", src.ID, "items", len(result.Items))
	}
	return cursor, result.Next, nil
}

func (m *Manager) stopAll(ctx context.Context) {
	m.mu.Lock()
	stopping := make([]*runningPoller, 0, len(m.pollers))
	for id, p := range m.pollers {
		m.log.InfoContext(ctx, "stopping poller on shutdown", "source_id", id)
		p.cancel()
		stopping = append(stopping, p)
	}
	m.pollers = make(map[string]*runningPoller)
	m.mu.Unlock()
	// Each poller releases its claim as it stops, so another replica takes the source at once.
	deadline := time.After(shutdownWait)
	for _, p := range stopping {
		select {
		case <-p.done:
		case <-deadline:
			m.log.WarnContext(ctx, "pollers did not stop in time; their claims expire on their own", "wait", shutdownWait)
			return
		}
	}
}

// shutdownWait bounds how long stopping waits for pollers to release their claims.
const shutdownWait = 5 * time.Second
