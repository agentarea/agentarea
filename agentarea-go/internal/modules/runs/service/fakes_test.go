package service

import (
	"bytes"
	"context"
	"errors"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"io"
	"iter"
	"log/slog"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

type memBlob struct {
	blob.Store
	mu sync.Mutex
	m  map[string][]byte
}

func newMemBlob() *memBlob { return &memBlob{m: map[string][]byte{}} }

func (b *memBlob) Put(_ context.Context, key string, body io.Reader, _ int64, _ blob.PutOptions) error {
	data, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.m[key] = data
	return nil
}

func (b *memBlob) Get(_ context.Context, key string) (io.ReadCloser, blob.Info, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	data, ok := b.m[key]
	if !ok {
		return nil, blob.Info{}, errors.New("not found")
	}
	return io.NopCloser(bytes.NewReader(data)), blob.Info{Key: key, Size: int64(len(data))}, nil
}

func (b *memBlob) List(_ context.Context, prefix string) iter.Seq2[blob.Info, error] {
	b.mu.Lock()
	var keys []string
	for k := range b.m {
		if strings.HasPrefix(k, prefix) {
			keys = append(keys, k)
		}
	}
	b.mu.Unlock()
	slices.Sort(keys)
	return func(yield func(blob.Info, error) bool) {
		for _, k := range keys {
			if !yield(blob.Info{Key: k}, nil) {
				return
			}
		}
	}
}

type fakeEvents struct {
	mu        sync.Mutex
	submitted []events.IntegrationEvent
	broadcast []events.IntegrationEvent
	runner    []map[string]string
}

func (f *fakeEvents) Submit(_ context.Context, e events.IntegrationEvent) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.submitted = append(f.submitted, e)
	return nil
}

func (f *fakeEvents) Broadcast(_ context.Context, e events.IntegrationEvent) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.broadcast = append(f.broadcast, e)
	return nil
}

func (f *fakeEvents) NotifyRunner(_ context.Context, clientID string, fields map[string]string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	fields["client"] = clientID
	f.runner = append(f.runner, fields)
	return nil
}

type fakeAudit struct {
	mu    sync.Mutex
	lines map[string]governanceapi.AuditRecord
}

func (f *fakeAudit) RecordOnce(_ context.Context, _ db.Session, l governanceapi.AuditRecord) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.lines == nil {
		f.lines = map[string]governanceapi.AuditRecord{}
	}
	if _, ok := f.lines[l.EventID]; !ok {
		f.lines[l.EventID] = l
	}
	return nil
}

type fakeModels struct {
	calls []modelsapi.Call
	reply modelsapi.Reply
	err   error
}

func (f *fakeModels) Call(_ context.Context, _ modelsapi.Principal, call modelsapi.Call) (modelsapi.Reply, error) {
	f.calls = append(f.calls, call)
	if f.err != nil {
		return modelsapi.Reply{}, f.err
	}
	if call.OnChunk != nil {
		call.OnChunk(modelsapi.Chunk{Delta: "thinking", Thinking: true})
		call.OnChunk(modelsapi.Chunk{Delta: f.reply.Content, Index: 1})
	}
	return f.reply, nil
}

type fakeTool struct {
	calls []ToolInvocation
	out   ToolOutput
	err   error
}

func (f *fakeTool) Call(_ context.Context, inv ToolInvocation) (ToolOutput, error) {
	f.calls = append(f.calls, inv)
	if inv.Progress != nil {
		total := 2.0
		inv.Progress(ToolProgress{Progress: 2, Total: &total, Message: "done"})
	}
	return f.out, f.err
}

type fakeBilling struct {
	hold    money.HoldDecision
	authErr error
	quote   *money.Decimal
	voided  []string
	authed  []money.AuthorizeRequest
}

func (f *fakeBilling) Currency() money.Currency { return "EUR" }

func (f *fakeBilling) Authorize(_ context.Context, req money.AuthorizeRequest) (money.HoldDecision, error) {
	f.authed = append(f.authed, req)
	return f.hold, f.authErr
}

func (f *fakeBilling) Capture(context.Context, money.CaptureRequest) (money.Charge, error) {
	return money.Charge{}, errors.New("not used")
}

func (f *fakeBilling) Void(_ context.Context, holdID string) error {
	f.voided = append(f.voided, holdID)
	return nil
}

func (f *fakeBilling) Quote(_ context.Context, lines []money.QuoteLine) ([]money.Quote, error) {
	out := make([]money.Quote, len(lines))
	for i := range lines {
		out[i] = money.Quote{Amount: f.quote, Code: "unpriced"}
	}
	return out, nil
}

type eurPricing struct{}

func (eurPricing) Currency() money.Currency { return "EUR" }

func testPrincipal() Principal {
	return Principal{WorkspaceID: "8b1f6d36-6a0e-4c43-9c43-1c2d8f0a2b11", UserID: "user-1", AgentID: "3f0c1a52-1d7e-4f0a-9a55-6c2e1b7d9e01"}
}

func quiet() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func fixedNow() time.Time { return time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC) }

type fakeRuntime struct {
	sandboxapi.Runtime
	mu         sync.Mutex
	files      map[string][]byte
	bash       []sandboxapi.BashCall
	validation sandboxapi.ArtifactValidation
}

func (f *fakeRuntime) Bash(_ context.Context, c sandboxapi.BashCall) (sandboxapi.ToolOutcome, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.bash = append(f.bash, c)
	return sandboxapi.ToolOutcome{Success: true, Result: "ran " + c.Command, Outcome: "exit"}, nil
}

func (f *fakeRuntime) PutFile(_ context.Context, _, _, path string, data []byte) (sandboxapi.StoredFile, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.files[path] = data
	return sandboxapi.StoredFile{Path: path, Size: int64(len(data))}, nil
}

func (f *fakeRuntime) ReadFile(_ context.Context, _, _, path string) ([]byte, string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	d, ok := f.files[path]
	if !ok {
		return nil, "", sandboxapi.ErrFileNotFound
	}
	return d, "text/plain", nil
}

func (f *fakeRuntime) ListFiles(context.Context, string, string, string) ([]string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for p := range f.files {
		out = append(out, p)
	}
	return out, nil
}

func (f *fakeRuntime) FileExists(_ context.Context, _, _, path string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	_, ok := f.files[path]
	return ok, nil
}

func (f *fakeRuntime) ValidateArtifacts(context.Context, string, string, []string) (sandboxapi.ArtifactValidation, error) {
	return f.validation, nil
}
