package storetest

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"iter"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"testing"
	"time"

	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// SourceTypes is the catalog's source types from the shipped data/catalog/source-types.json,
// plus any Extra rows ahead of them.
type SourceTypes struct {
	Rows []catalogapi.SourceTypeRow
}

// ShippedSourceTypes reads the shipped catalog.
func ShippedSourceTypes(t testing.TB, extra ...catalogapi.SourceTypeRow) *SourceTypes {
	t.Helper()
	_, here, _, _ := runtime.Caller(0)
	raw, err := os.ReadFile(filepath.Join(filepath.Dir(here), "..", "..", "..", "..", "..", "..", "data", "catalog", "source-types.json"))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		SourceTypes []json.RawMessage `json:"source_types"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	st := &SourceTypes{Rows: extra}
	for _, r := range doc.SourceTypes {
		var slug struct {
			Slug string `json:"slug"`
		}
		_ = json.Unmarshal(r, &slug)
		st.Rows = append(st.Rows, catalogapi.SourceTypeRow{Slug: slug.Slug, Spec: r})
	}
	return st
}

func (s *SourceTypes) SourceTypeRows(context.Context) ([]catalogapi.SourceTypeRow, error) {
	return s.Rows, nil
}

func (s *SourceTypes) SourceTypeRowsBySlug(_ context.Context, slug string) ([]catalogapi.SourceTypeRow, error) {
	var out []catalogapi.SourceTypeRow
	for _, r := range s.Rows {
		if r.Slug == slug {
			out = append(out, r)
		}
	}
	return out, nil
}

// Secrets is an in-memory secret store and reference index, shared by every workspace.
type Secrets struct {
	mu     sync.Mutex
	Values map[string]string
	Refs   map[string][]ksecrets.Reference
	// Fail makes every Get fail, as an unreachable store does.
	Fail bool
	// Named are the workspace secrets by id, for the catalog's GetForUse.
	Named map[string]ksecrets.Secret
	// Denied are secret ids the caller may not use.
	Denied map[string]bool
}

// NewSecrets is an empty store.
func NewSecrets() *Secrets {
	return &Secrets{Values: map[string]string{}, Refs: map[string][]ksecrets.Reference{}, Named: map[string]ksecrets.Secret{},
		Denied: map[string]bool{}}
}

type manager struct{ s *Secrets }

func (s *Secrets) Manager(db.Session, string) ksecrets.Manager { return manager{s} }

func (s *Secrets) Secret(_ context.Context, _ db.Session, id string) (ksecrets.Secret, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	sec, ok := s.Named[id]
	return sec, ok, nil
}

func (s *Secrets) SecretNamed(_ context.Context, _ db.Session, name string) (ksecrets.Secret, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, sec := range s.Named {
		if sec.Name == name {
			return sec, true, nil
		}
	}
	return ksecrets.Secret{}, false, nil
}

func (s *Secrets) StageReferences(_ context.Context, _ db.Session, consumerType, consumerID string, refs []ksecrets.Reference) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(refs) == 0 {
		delete(s.Refs, consumerType+":"+consumerID)
		return nil
	}
	s.Refs[consumerType+":"+consumerID] = refs
	return nil
}

func (m manager) Get(_ context.Context, name string) (string, error) {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	if m.s.Fail {
		return "", errors.New("secret store unreachable")
	}
	v, ok := m.s.Values[name]
	if !ok {
		return "", &ksecrets.NotFoundError{Message: name}
	}
	return v, nil
}

func (m manager) Set(_ context.Context, name, value string) error {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	m.s.Values[name] = value
	return nil
}

func (m manager) Delete(_ context.Context, name string) (bool, error) {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	_, ok := m.s.Values[name]
	delete(m.s.Values, name)
	return ok, nil
}

func (m manager) Has(_ context.Context, name string) (bool, error) {
	m.s.mu.Lock()
	defer m.s.mu.Unlock()
	_, ok := m.s.Values[name]
	return ok, nil
}

func (manager) ExternalRef(string) (string, bool) { return "", false }

// Catalog is the secret catalog over Secrets; only GetForUse is answered.
func (s *Secrets) Catalog(scope.Workspace, ksecrets.Actor) ksecrets.Catalog { return catalog{s: s} }

type catalog struct {
	ksecrets.Catalog
	s *Secrets
}

func (c catalog) GetForUse(_ context.Context, id string) (ksecrets.Secret, error) {
	c.s.mu.Lock()
	defer c.s.mu.Unlock()
	sec, ok := c.s.Named[id]
	switch {
	case !ok:
		return ksecrets.Secret{}, &ksecrets.NotFoundError{Message: "Secret not found"}
	case c.s.Denied[id]:
		return ksecrets.Secret{}, &ksecrets.AccessDeniedError{Message: "You may not use secret " + sec.Name}
	case sec.OwnerType != nil:
		return ksecrets.Secret{}, &ksecrets.ManagedError{Message: "managed"}
	}
	return sec, nil
}

// Bus records what is published.
type Bus struct {
	mu        sync.Mutex
	Published []Published
	Fail      error
}

// Published is one published event and its topic.
type Published struct {
	Event events.IntegrationEvent
	Topic string
}

func (b *Bus) Publish(_ context.Context, e events.IntegrationEvent, topic string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Fail != nil {
		return b.Fail
	}
	if _, err := events.Encode(e); err != nil {
		return err
	}
	b.Published = append(b.Published, Published{Event: e, Topic: topic})
	return nil
}

// Events is what was published.
func (b *Bus) Events() []Published {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]Published(nil), b.Published...)
}

// Dedup is an in-memory dedup cache.
type Dedup struct {
	mu   sync.Mutex
	Keys map[string]bool
}

func (d *Dedup) Claim(_ context.Context, key string, _ time.Duration) (bool, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.Keys == nil {
		d.Keys = map[string]bool{}
	}
	if d.Keys[key] {
		return false, nil
	}
	d.Keys[key] = true
	return true, nil
}

func (d *Dedup) Keep(context.Context, string) error { return nil }

func (d *Dedup) Contains(_ context.Context, key string) (bool, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.Keys[key], nil
}

func (d *Dedup) Release(_ context.Context, key string) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	delete(d.Keys, key)
	return nil
}

// Quota admits Limit events per workspace in total.
type Quota struct {
	mu    sync.Mutex
	Taken map[string]int
}

func (q *Quota) Admit(_ context.Context, ws string, limit int) (bool, error) {
	q.mu.Lock()
	defer q.mu.Unlock()
	if q.Taken == nil {
		q.Taken = map[string]int{}
	}
	if q.Taken[ws] >= limit {
		return false, nil
	}
	q.Taken[ws]++
	return true, nil
}

// Blob is an in-memory object store answering Put and Get.
type Blob struct {
	kblob.Store
	mu      sync.Mutex
	Objects map[string][]byte
}

func (b *Blob) Put(_ context.Context, key string, body io.Reader, _ int64, _ kblob.PutOptions) error {
	data, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Objects == nil {
		b.Objects = map[string][]byte{}
	}
	b.Objects[key] = data
	return nil
}

func (b *Blob) List(context.Context, string) iter.Seq2[kblob.Info, error] {
	return func(func(kblob.Info, error) bool) {}
}

// Keys is the stored object keys.
func (b *Blob) Keys() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]string, 0, len(b.Objects))
	for k := range b.Objects {
		out = append(out, k)
	}
	return out
}
