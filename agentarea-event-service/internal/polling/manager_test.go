package polling

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/secrets"
	"github.com/agentarea/event-service/internal/source"
	"github.com/agentarea/event-service/internal/template"
	"github.com/agentarea/event-service/internal/transport"
)

type fakeSources struct {
	mu         sync.Mutex
	list       []source.Source
	polled     map[string]string
	failed     map[string]string
	registered map[string]string
	subscribed []subscribed
	retryIn    map[string]time.Duration
	pollErr    error
}

type subscribed struct {
	id, url, subscriptionID, cursor string
	refreshBefore                   *time.Time
}

func newFakeSources(list ...source.Source) *fakeSources {
	return &fakeSources{
		list: list, polled: map[string]string{}, failed: map[string]string{}, registered: map[string]string{},
		retryIn: map[string]time.Duration{},
	}
}

func (f *fakeSources) Load(context.Context) ([]source.Source, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]source.Source(nil), f.list...), nil
}

func (f *fakeSources) Polled(_ context.Context, id, cursor string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.pollErr != nil {
		return f.pollErr
	}
	f.polled[id] = cursor
	return nil
}

func (f *fakeSources) Failed(_ context.Context, id, reason string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.failed[id] = reason
	return nil
}

func (f *fakeSources) SubscribeFailed(_ context.Context, id, reason string, retryIn time.Duration) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.failed[id] = reason
	f.retryIn[id] = retryIn
	return nil
}

func (f *fakeSources) Subscribed(_ context.Context, id, url, subscriptionID string, refreshBefore *time.Time, cursor string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.registered[id] = url
	f.subscribed = append(f.subscribed, subscribed{id: id, url: url, subscriptionID: subscriptionID, refreshBefore: refreshBefore, cursor: cursor})
	return nil
}

func (f *fakeSources) Registered(_ context.Context, id, url string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.registered[id] = url
	return nil
}

type published struct {
	sourceID string
	gap      string
	item     any
}

type fakePublisher struct {
	mu     sync.Mutex
	got    []published
	failAt int
}

func (f *fakePublisher) Item(_ context.Context, id string, item any) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.failAt > 0 && len(f.got)+1 == f.failAt {
		return errors.New("broker down")
	}
	f.got = append(f.got, published{sourceID: id, item: item})
	return nil
}

func (f *fakePublisher) Gap(_ context.Context, id, reason string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.got = append(f.got, published{sourceID: id, gap: reason})
	return nil
}

type call struct {
	url    string
	values template.Values
}

type fakeCaller struct {
	mu    sync.Mutex
	calls []call
	err   error
}

func (f *fakeCaller) Call(_ context.Context, req catalog.Request, v template.Values) ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, call{url: req.URL, values: v})
	return nil, f.err
}

type fakeClaimer struct{}

func (fakeClaimer) TryClaim(context.Context, string) (bool, error) { return true, nil }
func (fakeClaimer) Renew(context.Context, string) error            { return nil }
func (fakeClaimer) Release(context.Context, string) error          { return nil }

type noSecrets struct{}

func (noSecrets) Get(context.Context, string, string) (string, error) {
	return "", secrets.ErrNotFound
}

type fixedTransport struct {
	result    transport.Result
	err       error
	seen      []string
	instances []string
}

func (f *fixedTransport) Fetch(_ context.Context, fetch transport.Fetch) (transport.Result, error) {
	f.seen = append(f.seen, fetch.Values.Cursor)
	f.instances = append(f.instances, fetch.MCPInstanceID)
	return f.result, f.err
}

func newManager(src *fakeSources, pub *fakePublisher, caller *fakeCaller, tr transport.Transport) *Manager {
	return NewManager(Deps{
		Sources:    src,
		Secrets:    noSecrets{},
		Transports: transport.Set{"fixed": tr},
		Publisher:  pub,
		Caller:     caller,
		Claimer:    fakeClaimer{},
		APIURL:     "https://api.example.com",
		Interval:   time.Hour,
		MaxPollers: 10,
	})
}

func pollSource() source.Source {
	return source.Source{
		ID: "src-1", WorkspaceID: "ws", Kind: source.KindPoll, Slug: "feedy", Cursor: "c0",
		Entry: catalog.Entry{Slug: "feedy", Poll: &catalog.Poll{Transport: "fixed", Interval: "1h"}},
	}
}

func TestAPollPublishesTheGapThenItemsInOrderThenStoresTheCursor(t *testing.T) {
	src := newFakeSources()
	pub := &fakePublisher{}
	tr := &fixedTransport{result: transport.Result{Items: []any{"a", "b"}, Cursor: "c2", Gap: "renumbered"}}
	m := newManager(src, pub, &fakeCaller{}, tr)

	next, _, err := m.pollOnce(context.Background(), pollSource(), tr, "c0")
	if err != nil {
		t.Fatalf("pollOnce: %v", err)
	}
	if next != "c2" || src.polled["src-1"] != "c2" || tr.seen[0] != "c0" {
		t.Fatalf("next = %q, stored = %q, asked with %v", next, src.polled["src-1"], tr.seen)
	}
	if len(pub.got) != 3 || pub.got[0].gap != "renumbered" || pub.got[1].item != "a" || pub.got[2].item != "b" {
		t.Fatalf("published = %+v", pub.got)
	}
}

func TestAFailedPublishDoesNotMoveTheCursor(t *testing.T) {
	src := newFakeSources()
	pub := &fakePublisher{failAt: 2}
	tr := &fixedTransport{result: transport.Result{Items: []any{"a", "b"}, Cursor: "c2"}}
	m := newManager(src, pub, &fakeCaller{}, tr)

	next, _, err := m.pollOnce(context.Background(), pollSource(), tr, "c0")
	if err == nil {
		t.Fatal("a failed publish reported success")
	}
	if next != "c0" {
		t.Fatalf("cursor moved to %q", next)
	}
	if _, stored := src.polled["src-1"]; stored {
		t.Fatal("the cursor was stored after a failed publish")
	}
}

func TestNothingNewKeepsTheStoredCursor(t *testing.T) {
	src := newFakeSources()
	tr := &fixedTransport{}
	m := newManager(src, &fakePublisher{}, &fakeCaller{}, tr)

	next, _, err := m.pollOnce(context.Background(), pollSource(), tr, "c0")
	if err != nil || next != "c0" {
		t.Fatalf("next = %q, err = %v", next, err)
	}
	if cursor, ok := src.polled["src-1"]; !ok || cursor != "" {
		t.Fatalf("stored = %q, %v; want the poll recorded with the cursor kept", cursor, ok)
	}
}

func TestAPollErrorIsRecordedOnTheSource(t *testing.T) {
	src := newFakeSources(pollSource())
	tr := &fixedTransport{err: errors.New("HTTP 502")}
	m := newManager(src, &fakePublisher{}, &fakeCaller{}, tr)

	ctx, cancel := context.WithCancel(context.Background())
	m.reconcile(ctx)
	deadline := time.Now().Add(5 * time.Second)
	for {
		src.mu.Lock()
		reason := src.failed["src-1"]
		src.mu.Unlock()
		if reason == "HTTP 502" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("failure not recorded: %v", src.failed)
		}
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
}

func webhookSource(registeredURL string) source.Source {
	return source.Source{
		ID: "src-w", WorkspaceID: "ws", Kind: source.KindWebhook, Slug: "chat", WebhookID: "w1",
		RegisteredURL: registeredURL,
		Entry: catalog.Entry{Slug: "chat", Registration: &catalog.Registration{
			Register:   &catalog.Request{Method: "POST", URL: "https://chat.example/set"},
			Unregister: &catalog.Request{Method: "POST", URL: "https://chat.example/delete"},
		}},
	}
}

func TestAWebhookSourceIsRegisteredWithItsURL(t *testing.T) {
	src := newFakeSources(webhookSource(""))
	caller := &fakeCaller{}
	m := newManager(src, &fakePublisher{}, caller, &fixedTransport{})

	m.reconcile(context.Background())
	if len(caller.calls) != 1 || caller.calls[0].url != "https://chat.example/set" ||
		caller.calls[0].values.WebhookURL != "https://api.example.com/webhooks/w1" {
		t.Fatalf("calls = %+v", caller.calls)
	}
	if src.registered["src-w"] != "https://api.example.com/webhooks/w1" {
		t.Fatalf("registered = %v", src.registered)
	}
}

func TestARegisteredSourceIsNotRegisteredAgain(t *testing.T) {
	src := newFakeSources(webhookSource("https://api.example.com/webhooks/w1"))
	caller := &fakeCaller{}
	m := newManager(src, &fakePublisher{}, caller, &fixedTransport{})

	m.reconcile(context.Background())
	if len(caller.calls) != 0 {
		t.Fatalf("calls = %+v", caller.calls)
	}
}

func TestAFailedRegistrationIsRecordedAndRetried(t *testing.T) {
	src := newFakeSources(webhookSource(""))
	caller := &fakeCaller{err: errors.New("HTTP 401")}
	m := newManager(src, &fakePublisher{}, caller, &fixedTransport{})

	m.reconcile(context.Background())
	m.reconcile(context.Background())
	if len(caller.calls) != 2 || src.failed["src-w"] != "registration: HTTP 401" || src.registered["src-w"] != "" {
		t.Fatalf("calls = %d, failed = %v, registered = %v", len(caller.calls), src.failed, src.registered)
	}
}

func TestADeletedSourceIsUnregistered(t *testing.T) {
	src := newFakeSources(webhookSource(""))
	caller := &fakeCaller{}
	m := newManager(src, &fakePublisher{}, caller, &fixedTransport{})

	m.reconcile(context.Background())
	src.mu.Lock()
	src.list = nil
	src.mu.Unlock()
	m.reconcile(context.Background())

	if len(caller.calls) != 2 || caller.calls[1].url != "https://chat.example/delete" {
		t.Fatalf("calls = %+v", caller.calls)
	}
	m.reconcile(context.Background())
	if len(caller.calls) != 2 {
		t.Fatalf("unregistered twice: %+v", caller.calls)
	}
}
