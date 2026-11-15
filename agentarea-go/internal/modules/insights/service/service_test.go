package service

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

type fakeDB struct{ db.Database }

func (fakeDB) Global() db.Global { return nil }

type fakeInstallations struct {
	id    string
	calls int
	now   time.Time
	err   error
}

func (f *fakeInstallations) GetOrCreate(_ context.Context, _ db.Global, now time.Time) (string, error) {
	f.calls++
	f.now = now
	return f.id, f.err
}

type fakeBalance struct {
	b   money.AccountBalance
	err error
}

func (f fakeBalance) Balance(context.Context, authn.Caller) (money.AccountBalance, error) {
	return f.b, f.err
}

func caller(t *testing.T) authn.Caller {
	t.Helper()
	ws, err := scope.NewWorkspace("0195a0a0-0000-7000-8000-000000000001", "acme")
	if err != nil {
		t.Fatal(err)
	}
	return authn.Caller{Workspace: ws}
}

func TestAnalyticsOffTouchesNothing(t *testing.T) {
	inst := &fakeInstallations{id: "unused"}
	s := New(Deps{DB: fakeDB{}, Installations: inst, Log: slog.New(slog.DiscardHandler)})
	a, err := s.Analytics(context.Background())
	if err != nil || a.Enabled || a.InstallID != nil || a.CollectorURL != nil || a.Edition != nil {
		t.Fatalf("analytics off: %+v %v", a, err)
	}
	if inst.calls != 0 {
		t.Fatal("analytics off created an installation")
	}
}

func TestAnalyticsOnReturnsInstallation(t *testing.T) {
	at := time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC)
	inst := &fakeInstallations{id: "abc"}
	s := New(Deps{DB: fakeDB{}, Installations: inst, AnalyticsEnabled: true, Edition: "oss",
		Now: func() time.Time { return at }, Log: slog.New(slog.DiscardHandler)})
	a, err := s.Analytics(context.Background())
	if err != nil || !a.Enabled || *a.InstallID != "abc" || *a.CollectorURL != collectorURL || *a.Edition != "oss" {
		t.Fatalf("analytics on: %+v %v", a, err)
	}
	if !inst.now.Equal(at) {
		t.Fatalf("installation written at %v, want %v", inst.now, at)
	}
}

const collectorURL = "https://analytics.agentarea.ai"

func TestBalanceNoSourceIsNull(t *testing.T) {
	s := New(Deps{DB: fakeDB{}, Log: slog.New(slog.DiscardHandler)})
	b, err := s.Balance(context.Background(), caller(t))
	if err != nil || b != nil {
		t.Fatalf("balance without a source: %+v %v", b, err)
	}
}

func TestBalanceRendersDecimalsAndHidesAmountForNonPayer(t *testing.T) {
	src := fakeBalance{b: money.AccountBalance{Currency: "USD", ViewerIsPayer: false, Exhausted: true,
		SpendPerDay: ptr(money.MustParse("1.50")), RunwayDays: ptr(money.MustParse("3"))}}
	s := New(Deps{DB: fakeDB{}, Balance: src, Log: slog.New(slog.DiscardHandler)})
	b, err := s.Balance(context.Background(), caller(t))
	if err != nil || b == nil || b.Amount != nil || *b.SpendPerDay != "1.50" || *b.RunwayDays != "3" || b.Currency != "USD" || !b.Exhausted {
		t.Fatalf("balance: %+v %v", b, err)
	}
}

func TestBalanceSourceFailureIsUnavailable(t *testing.T) {
	s := New(Deps{DB: fakeDB{}, Balance: fakeBalance{err: errors.New("db down")}, Log: slog.New(slog.DiscardHandler)})
	if _, err := s.Balance(context.Background(), caller(t)); !errors.Is(err, ErrBalanceUnavailable) {
		t.Fatalf("got %v, want ErrBalanceUnavailable", err)
	}
}

func TestBalanceSourceHTTPErrorPassesThrough(t *testing.T) {
	want := httpx.HTTPError(402, "insufficient")
	s := New(Deps{DB: fakeDB{}, Balance: fakeBalance{err: want}, Log: slog.New(slog.DiscardHandler)})
	if _, err := s.Balance(context.Background(), caller(t)); !errors.Is(err, want) {
		t.Fatalf("got %v, want the source's HTTP error", err)
	}
}

func ptr(d money.Decimal) *money.Decimal { return &d }
