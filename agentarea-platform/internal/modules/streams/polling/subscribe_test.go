package polling

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

type fakeMCP struct {
	mu           sync.Mutex
	subscribes   []mcpSubscribe
	unsubscribes []mcpUnsubscribe
	grant        SubscribeResult
	err          error
}

type mcpSubscribe struct {
	instance string
	req      SubscribeRequest
}

type mcpUnsubscribe struct {
	instance string
	req      UnsubscribeRequest
}

func (f *fakeMCP) Subscribe(_ context.Context, instance string, req SubscribeRequest) (SubscribeResult, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.subscribes = append(f.subscribes, mcpSubscribe{instance: instance, req: req})
	return f.grant, f.err
}

func (f *fakeMCP) Unsubscribe(_ context.Context, instance string, req UnsubscribeRequest) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.unsubscribes = append(f.unsubscribes, mcpUnsubscribe{instance: instance, req: req})
	return f.err
}

const mcpSecret = "whsec_bWJtYm1ibWJtYm1ibWJtYm1ibWJtYm1ibWJtYm1i" // pragma: allowlist secret

func mcpSource() Source {
	return Source{
		ID: "src-m", WorkspaceID: "11111111-1111-1111-1111-111111111111", Kind: KindWebhook, Slug: "mcp_events", WebhookID: "wm",
		CredentialKey: "src-m", Cursor: "c-stored", MCPInstanceID: "inst-1",
		Config: map[string]any{"mcp_instance_id": "inst-1", "event": "ticket.created", "arguments": `{"queue":"support"}`},
		Entry:  Entry{Slug: "mcp_events", Registration: &Registration{Transport: "mcp_events"}},
	}
}

func newMCPManager(src *fakeSources, mcp *fakeMCP) *Manager {
	credentials := func(_ context.Context, _ scope.Workspace, _, slug, key string) (map[string]string, error) {
		if slug != "mcp_events" || key != "src-m" {
			return nil, errors.New("no credentials")
		}
		return map[string]string{"signing_secret": mcpSecret}, nil
	}
	return NewManager(Deps{
		Sources:     src,
		Credentials: credentials,
		Transports:  Transports{},
		Intake:      &fakePublisher{},
		Caller:      &fakeCaller{},
		MCP:         mcp,
		Claimer:     fakeClaimer{},
		WebhookURL:  webhookURL,
		Interval:    30 * time.Second,
		MaxPollers:  10,
	})
}

func TestAnMCPWebhookSourceIsSubscribedWithItsURLAndIssuedSecret(t *testing.T) {
	refresh := time.Now().Add(time.Hour).UTC()
	mcp := &fakeMCP{grant: SubscribeResult{ID: "sub_1", RefreshBefore: &refresh, Cursor: ptr("c-0")}}
	src := newFakeSources(mcpSource())
	newMCPManager(src, mcp).reconcile(context.Background())

	if len(mcp.subscribes) != 1 {
		t.Fatalf("subscribes = %+v", mcp.subscribes)
	}
	got := mcp.subscribes[0]
	if got.instance != "inst-1" || got.req.Name != "ticket.created" || got.req.Arguments["queue"] != "support" {
		t.Fatalf("subscribe = %+v", got)
	}
	if got.req.Delivery.URL != "https://api.example.com/webhooks/wm" || got.req.Delivery.Secret != mcpSecret { // pragma: allowlist secret
		t.Fatalf("delivery = %+v", got.req.Delivery)
	}
	if got.req.Cursor == nil || *got.req.Cursor != "c-stored" || got.req.TTLMs <= 0 {
		t.Fatalf("cursor/ttl = %v/%d", got.req.Cursor, got.req.TTLMs)
	}
	if len(src.subscribed) != 1 || src.subscribed[0].subscriptionID != "sub_1" || src.subscribed[0].cursor != "c-0" ||
		!src.subscribed[0].refreshBefore.Equal(refresh) || src.subscribed[0].url != "https://api.example.com/webhooks/wm" {
		t.Fatalf("recorded = %+v", src.subscribed)
	}
}

func subscribedSource(refreshBefore *time.Time) Source {
	s := mcpSource()
	s.RegisteredURL = "https://api.example.com/webhooks/wm"
	s.SubscriptionID = "sub_1"
	s.RefreshBefore = refreshBefore
	return s
}

func TestAnMCPSubscriptionIsRefreshedBeforeItExpiresAndNotBefore(t *testing.T) {
	soon := time.Now().Add(20 * time.Second)
	later := time.Now().Add(2 * time.Hour)
	grant := time.Now().Add(time.Hour)
	for name, tc := range map[string]struct {
		refreshBefore *time.Time
		want          int
	}{
		"expiring":  {&soon, 1},
		"fresh":     {&later, 0},
		"no expiry": {nil, 0},
	} {
		mcp := &fakeMCP{grant: SubscribeResult{ID: "sub_1", RefreshBefore: &grant}}
		newMCPManager(newFakeSources(subscribedSource(tc.refreshBefore)), mcp).reconcile(context.Background())
		if len(mcp.subscribes) != tc.want {
			t.Fatalf("%s: subscribes = %d, want %d", name, len(mcp.subscribes), tc.want)
		}
	}
}

func TestADeletedMCPSourceIsUnsubscribed(t *testing.T) {
	later := time.Now().Add(2 * time.Hour)
	src := newFakeSources(subscribedSource(&later))
	mcp := &fakeMCP{}
	m := newMCPManager(src, mcp)

	m.reconcile(context.Background())
	src.mu.Lock()
	src.list = nil
	src.mu.Unlock()
	m.reconcile(context.Background())
	m.reconcile(context.Background())

	if len(mcp.unsubscribes) != 1 {
		t.Fatalf("unsubscribes = %+v", mcp.unsubscribes)
	}
	got := mcp.unsubscribes[0]
	if got.instance != "inst-1" || got.req.Name != "ticket.created" || got.req.Arguments["queue"] != "support" ||
		got.req.Delivery.URL != "https://api.example.com/webhooks/wm" {
		t.Fatalf("unsubscribe = %+v", got)
	}
}

func TestAFailedMCPSubscriptionIsRecorded(t *testing.T) {
	src := newFakeSources(mcpSource())
	mcp := &fakeMCP{err: &RPCError{Code: -32027, Message: "CallbackEndpointError"}}
	newMCPManager(src, mcp).reconcile(context.Background())
	if src.failed["src-m"] == "" || len(src.subscribed) != 0 {
		t.Fatalf("failed = %v, subscribed = %v", src.failed, src.subscribed)
	}
}

func TestAnMCPSourceNamingAServerOfAnotherWorkspaceIsNotSubscribed(t *testing.T) {
	foreign := mcpSource()
	foreign.MCPInstanceID = ""
	src := newFakeSources(foreign)
	mcp := &fakeMCP{err: errors.New("must not be called")}
	newMCPManager(src, mcp).reconcile(context.Background())
	if len(mcp.subscribes) != 0 || src.failed["src-m"] == "" {
		t.Fatalf("subscribes = %d, failed = %v", len(mcp.subscribes), src.failed)
	}
}

// failingSource is an mcp_events source whose last attempt failed and was put
// off for prev; it has been due again for dueAgo (negative: not yet due).
func failingSource(prev, dueAgo time.Duration) Source {
	s := mcpSource()
	retryAt := time.Now().Add(-dueAgo)
	attempted := retryAt.Add(-prev)
	s.PollError = "subscription: CallbackEndpointError"
	s.PolledAt = &attempted
	s.RefreshBefore = &retryAt
	return s
}

func TestAFailingMCPSubscriptionBacksOffExponentiallyUpToAnHour(t *testing.T) {
	for name, tc := range map[string]struct {
		src  Source
		want time.Duration
	}{
		"first failure":         {mcpSource(), 30 * time.Second},
		"after terminated":      {func() Source { s := mcpSource(); s.PollError = "terminated: Forbidden"; return s }(), 30 * time.Second},
		"second failure":        {failingSource(30*time.Second, time.Second), time.Minute},
		"fourth failure":        {failingSource(2*time.Minute, time.Second), 4 * time.Minute},
		"capped":                {failingSource(45*time.Minute, time.Second), time.Hour},
		"stays capped":          {failingSource(time.Hour, time.Second), time.Hour},
		"refresh of live grant": {subscribedSource(ptrTime(time.Now().Add(10 * time.Second))), 30 * time.Second},
	} {
		src := newFakeSources(tc.src)
		mcp := &fakeMCP{err: &RPCError{Code: -32027, Message: "CallbackEndpointError"}}
		newMCPManager(src, mcp).reconcile(context.Background())
		if len(mcp.subscribes) != 1 || src.failed["src-m"] == "" || src.retryIn["src-m"] != tc.want {
			t.Fatalf("%s: subscribes = %d, failed = %q, retry in %v, want %v",
				name, len(mcp.subscribes), src.failed["src-m"], src.retryIn["src-m"], tc.want)
		}
	}
}

func TestAnMCPSourceBackingOffIsNeitherSubscribedNorRewritten(t *testing.T) {
	waiting := failingSource(time.Minute, -40*time.Second)
	foreign := failingSource(time.Minute, -40*time.Second)
	foreign.MCPInstanceID = ""
	for name, s := range map[string]Source{"server failing": waiting, "no server": foreign} {
		src := newFakeSources(s)
		mcp := &fakeMCP{err: errors.New("must not be called")}
		newMCPManager(src, mcp).reconcile(context.Background())
		if len(mcp.subscribes) != 0 || len(src.failed) != 0 || len(src.retryIn) != 0 {
			t.Fatalf("%s: subscribes = %d, failed = %v", name, len(mcp.subscribes), src.failed)
		}
	}
}

func TestAnMCPSubscriptionThatSucceedsAfterFailuresIsRecordedWithItsGrant(t *testing.T) {
	grant := time.Now().Add(time.Hour).UTC()
	src := newFakeSources(failingSource(8*time.Minute, time.Second))
	mcp := &fakeMCP{grant: SubscribeResult{ID: "sub_2", RefreshBefore: &grant}}
	newMCPManager(src, mcp).reconcile(context.Background())
	if len(src.subscribed) != 1 || src.subscribed[0].subscriptionID != "sub_2" || !src.subscribed[0].refreshBefore.Equal(grant) ||
		len(src.retryIn) != 0 {
		t.Fatalf("subscribed = %+v, retry = %v", src.subscribed, src.retryIn)
	}
}

func TestADeletedMCPSourceBackingOffWithNoSubscriptionIsNotUnsubscribed(t *testing.T) {
	src := newFakeSources(failingSource(time.Minute, -40*time.Second))
	mcp := &fakeMCP{}
	m := newMCPManager(src, mcp)
	m.reconcile(context.Background())
	src.mu.Lock()
	src.list = nil
	src.mu.Unlock()
	m.reconcile(context.Background())
	if len(mcp.unsubscribes) != 0 {
		t.Fatalf("unsubscribes = %+v", mcp.unsubscribes)
	}
}

func ptrTime(t time.Time) *time.Time { return &t }

func TestAPollHandsTheTransportTheSourcesMCPServerAndItsWait(t *testing.T) {
	src := newFakeSources()
	tr := &fixedTransport{result: Result{Cursor: "c1", Next: 3 * time.Second}}
	m := newManager(src, &fakePublisher{}, &fakeCaller{}, tr)
	poll := pollSource()
	poll.MCPInstanceID = "inst-9"

	_, wait, err := m.pollOnce(context.Background(), poll, tr, "c0")
	if err != nil || wait != 3*time.Second || tr.instances[0] != "inst-9" {
		t.Fatalf("wait = %v, instances = %v, err = %v", wait, tr.instances, err)
	}
}
