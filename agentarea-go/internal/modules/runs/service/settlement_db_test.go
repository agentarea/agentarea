package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

type settleBilling struct {
	mu       sync.Mutex
	captures []money.CaptureRequest
	// during runs inside Capture; captureErr is its answer when set.
	during     func(money.CaptureRequest) error
	captureErr error
	quotes     []money.QuoteLine
	quoteErr   error
	quote      money.Decimal
}

func (*settleBilling) Currency() money.Currency { return "EUR" }

func (*settleBilling) Authorize(context.Context, money.AuthorizeRequest) (money.HoldDecision, error) {
	return money.HoldDecision{}, errors.New("not used")
}

func (b *settleBilling) Capture(_ context.Context, req money.CaptureRequest) (money.Charge, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.captures = append(b.captures, req)
	if b.during != nil {
		if err := b.during(req); err != nil {
			return money.Charge{}, err
		}
	}
	if b.captureErr != nil {
		return money.Charge{}, b.captureErr
	}
	return money.Charge{Amount: money.MustParse("1.25"), Currency: "EUR"}, nil
}

func (*settleBilling) Void(context.Context, string) error { return nil }

func (b *settleBilling) Quote(_ context.Context, lines []money.QuoteLine) ([]money.Quote, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.quotes = append(b.quotes, lines...)
	if b.quoteErr != nil {
		return nil, b.quoteErr
	}
	q := b.quote
	return []money.Quote{{Amount: &q}}, nil
}

type fakeVendor struct {
	decl   map[string]any
	status int
	body   string
	urls   []string
}

func (v *fakeVendor) SettledDeclaration(context.Context, scope.Workspace, string, string, string) (map[string]any, error) {
	return v.decl, nil
}

func (v *fakeVendor) FetchSettlement(_ context.Context, _ scope.Workspace, _, _, url string) (int, []byte, error) {
	v.urls = append(v.urls, url)
	return v.status, []byte(v.body), nil
}

// waiting writes a line waiting on settlement, as a run records it.
func waiting(t *testing.T, d db.Database, p Principal, taskID string, l domain.CostLine) domain.CostLine {
	t.Helper()
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	l.EventID, l.TaskID, l.AgentID = uuid.NewString(), taskID, p.AgentID
	if l.OccurredAt.IsZero() {
		l.OccurredAt = time.Now().Add(-time.Second)
	}
	err := d.Write(context.Background(), ws, func(ctx context.Context, s db.Session) error {
		_, err := store.Runs{}.InsertCostLine(ctx, s, l, p.UserID, store.TaskRef{ID: taskID, CorrelationID: "corr-1"})
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return l
}

type ledgerRow struct {
	EventID, Amount, Currency, Source string
	Estimate                          bool
	Evidence                          map[string]any
	Supersedes                        *string
	VendorCost                        *string
	Correlation                       *string
}

func ledger(t *testing.T, d db.Database, p Principal) []ledgerRow {
	t.Helper()
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	s, release, err := d.Read(context.Background(), ws)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	rows, err := s.Q().Query(context.Background(), `SELECT event_id::text, amount::text, COALESCE(currency, ''), source, estimate,
		evidence::text, supersedes_id::text, vendor_cost::text, correlation_id FROM cost_entries WHERE workspace_id = $1 ORDER BY occurred_at, supersedes_id NULLS FIRST, id`, p.WorkspaceID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var out []ledgerRow
	for rows.Next() {
		var r ledgerRow
		var ev string
		if err := rows.Scan(&r.EventID, &r.Amount, &r.Currency, &r.Source, &r.Estimate, &ev, &r.Supersedes, &r.VendorCost, &r.Correlation); err != nil {
			t.Fatal(err)
		}
		_ = json.Unmarshal([]byte(ev), &r.Evidence)
		out = append(out, r)
	}
	return out
}

func settleUntilIdle(t *testing.T, s *Service) int {
	t.Helper()
	total := 0
	for range 10 {
		n, err := s.SettleBatch(context.Background(), time.Now())
		if err != nil {
			t.Fatal(err)
		}
		if n == 0 {
			return total
		}
		total += n
	}
	t.Fatal("settlement never went idle")
	return total
}

func TestSettlementCapturesAHoldOnce(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	line := waiting(t, d, p, taskID, domain.CostLine{
		Category: domain.CostModel, SubjectType: domain.SubjectModelInstance, SubjectID: ptr("gpt-x"), SubjectName: ptr("GPT"),
		Amount: "2.000000000000", Currency: "EUR", Source: domain.SourceTokenPricing, Payer: domain.PayerPlatform,
		VendorCost: ptr("0.8"), VendorCurrency: ptr("USD"), Estimate: true,
		Evidence: map[string]any{"settle": "capture", "hold_id": "hold-1", "iteration": 3},
	})

	if n := settleUntilIdle(t, s); n != 1 {
		t.Fatalf("settled %d lines, want 1", n)
	}
	if len(bill.captures) != 1 {
		t.Fatalf("captured %d times, want once", len(bill.captures))
	}
	c := bill.captures[0]
	if c.HoldID != "hold-1" || c.Connector != "llm" || c.Tool != "gpt-x" || c.Kind != money.KindModel ||
		c.IdempotencyKey != "tool:"+line.EventID || c.VendorCost.String() != "0.800000000000" || c.Unit != "call" {
		t.Fatalf("capture %+v", c)
	}
	rows := ledger(t, d, p)
	if len(rows) != 2 {
		t.Fatalf("ledger %+v", rows)
	}
	got := rows[1]
	want := uuid.NewSHA1(uuid.MustParse(settledLines), []byte(line.EventID+":capture")).String()
	if got.EventID != want || got.Amount != "1.250000000000" || got.Currency != "EUR" || got.Estimate ||
		got.Supersedes == nil || got.Source != domain.SourceTokenPricing || !sameCorrelation(t, d, p, taskID, got.Correlation) {
		t.Fatalf("successor %+v", got)
	}
	if _, kept := got.Evidence["settle"]; kept || got.Evidence["hold_id"] != "hold-1" {
		t.Fatalf("successor evidence %v", got.Evidence)
	}
}

func TestSettlementSharesLinesAcrossWorkers(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	const lines = 45
	for range lines {
		waiting(t, d, p, taskID, domain.CostLine{
			Category: domain.CostService, SubjectType: domain.SubjectTool, SubjectID: ptr(uuid.NewString()), SubjectName: ptr("search"),
			Amount: "1", Currency: "EUR", Source: "rate", Payer: domain.PayerPlatform, VendorCost: ptr("1"), VendorCurrency: ptr("USD"),
			Estimate: true, Evidence: map[string]any{"settle": "capture", "hold_id": uuid.NewString(), "connector": "acme"},
		})
	}
	var wg sync.WaitGroup
	for range 4 {
		wg.Go(func() {
			for range 5 {
				if _, err := s.SettleBatch(context.Background(), time.Now()); err != nil {
					t.Error(err)
				}
			}
		})
	}
	wg.Wait()
	settleUntilIdle(t, s)
	if len(bill.captures) != lines {
		t.Fatalf("captured %d times for %d lines", len(bill.captures), lines)
	}
	seen := map[string]bool{}
	for _, c := range bill.captures {
		if seen[c.HoldID] {
			t.Fatalf("hold %s captured twice", c.HoldID)
		}
		seen[c.HoldID] = true
	}
	if got := len(ledger(t, d, p)); got != 2*lines {
		t.Fatalf("ledger has %d lines, want %d", got, 2*lines)
	}
}

func TestSettlementConvertsAPendingConversion(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{quoteErr: errors.New("fx down")}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	waiting(t, d, p, taskID, domain.CostLine{
		Category: domain.CostModel, SubjectType: domain.SubjectModelInstance, SubjectID: ptr("m-1"), SubjectName: ptr("M"),
		Amount: "0.5", Currency: "USD", Source: domain.SourceTokenPricing, Payer: domain.PayerWorkspace,
		VendorCost: ptr("0.5"), VendorCurrency: ptr("USD"), Estimate: true, Evidence: map[string]any{"settle": "convert", "vendor_exact": true},
	})
	if n := settleUntilIdle(t, s); n != 0 {
		t.Fatalf("a conversion billing could not make settled %d lines", n)
	}
	bill.quoteErr, bill.quote = nil, money.MustParse("0.46")
	if n := settleUntilIdle(t, s); n != 1 {
		t.Fatalf("settled %d, want 1", n)
	}
	rows := ledger(t, d, p)
	if len(rows) != 2 || rows[1].Amount != "0.460000000000" || rows[1].Currency != "EUR" || rows[1].Estimate {
		t.Fatalf("ledger %+v", rows)
	}
	last := bill.quotes[len(bill.quotes)-1]
	if last.Kind != money.KindModel || last.Payer != "workspace" || last.VendorCurrency != "USD" {
		t.Fatalf("a model line is quoted as a model's, without markup: %+v", last)
	}
}

func TestSettlementReadsTheVendorTwiceBeforeTrustingIt(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{quote: money.MustParse("9")}
	vendor := &fakeVendor{status: 200, body: `{"run": {"status": "SUCCEEDED", "usd": 0.37}}`, decl: map[string]any{
		"source": "settled", "estimate": map[string]any{"amount": "1", "currency": "USD"},
		"settled": map[string]any{"fetch": map[string]any{
			"url": "https://api.vendor.test/runs/{run}", "params": map[string]any{"run": "$.id"},
			"cost": "$.run.usd", "currency": "USD", "done": map[string]any{"path": "$.run.status", "in": []any{"SUCCEEDED"}},
		}},
	}}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Vendor: vendor, Log: quiet()})
	waiting(t, d, p, taskID, domain.CostLine{
		Category: domain.CostService, SubjectType: domain.SubjectTool, SubjectID: ptr(uuid.NewString()), SubjectName: ptr("crawl"),
		Amount: "1", Currency: "USD", Source: "settled", Payer: domain.PayerWorkspace, VendorCost: ptr("1"), VendorCurrency: ptr("USD"),
		Estimate: true, Evidence: map[string]any{"settle": "vendor", "settle_params": map[string]any{"run": "a b/c"}, "connector": "acme"},
	})
	if n := settleUntilIdle(t, s); n != 2 {
		t.Fatalf("settled %d steps, want a read then its confirmation", n)
	}
	if vendor.urls[0] != "https://api.vendor.test/runs/a%20b%2Fc" {
		t.Fatalf("url %s", vendor.urls[0])
	}
	rows := ledger(t, d, p)
	if len(rows) != 3 {
		t.Fatalf("ledger %+v", rows)
	}
	read, final := rows[1], rows[2]
	if final.Evidence["settle"] == "vendor" {
		read, final = final, read
	}
	if !read.Estimate || read.Evidence["settle"] != "vendor" || read.VendorCost == nil || *read.VendorCost != "0.370000000000" || read.Source != "settled" {
		t.Fatalf("first read %+v", read)
	}
	if final.Estimate || final.Amount != "9.000000000000" || final.Currency != "EUR" || final.Evidence["settle"] != nil {
		t.Fatalf("confirmed line %+v", final)
	}
}

func TestSettlementWaitsWhileTheVendorIsNotDone(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	vendor := &fakeVendor{status: 200, body: `{"run": {"status": "RUNNING", "usd": 0}}`, decl: map[string]any{
		"source": "settled", "settled": map[string]any{"fetch": map[string]any{
			"url": "https://api.vendor.test/runs/{run}", "params": map[string]any{"run": "$.id"},
			"cost": "$.run.usd", "currency": "USD", "done": map[string]any{"path": "$.run.status", "in": []any{"SUCCEEDED"}},
		}},
	}}
	s := New(Deps{DB: d, Pricing: eurPricing{}, Vendor: vendor, Log: quiet()})
	waiting(t, d, p, taskID, domain.CostLine{
		Category: domain.CostService, SubjectType: domain.SubjectTool, SubjectID: ptr(uuid.NewString()), SubjectName: ptr("crawl"),
		Amount: "0", Currency: "USD", Source: "settled", Payer: domain.PayerWorkspace, VendorCost: ptr("0"), VendorCurrency: ptr("USD"),
		Estimate: true, Evidence: map[string]any{"settle": "vendor", "settle_params": map[string]any{"run": "r1"}},
	})
	if n := settleUntilIdle(t, s); n != 0 || len(vendor.urls) == 0 {
		t.Fatalf("settled %d while the vendor runs (%d reads)", n, len(vendor.urls))
	}
}

func TestSettlementLeavesAnUnknownKindAndALineWithoutBilling(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	s := New(Deps{DB: d, Pricing: eurPricing{}, Log: quiet()})
	for _, kind := range []string{"capture", "teleport"} {
		waiting(t, d, p, taskID, domain.CostLine{
			Category: domain.CostService, SubjectType: domain.SubjectTool, Amount: "1", Currency: "EUR", Source: "rate",
			Payer: domain.PayerPlatform, Estimate: true, Evidence: map[string]any{"settle": kind, "hold_id": "h"},
		})
	}
	if n := settleUntilIdle(t, s); n != 0 {
		t.Fatalf("settled %d", n)
	}
	if got := len(ledger(t, d, p)); got != 2 {
		t.Fatalf("ledger has %d lines", got)
	}
}

func TestSettlementLeavesLinesPastTheHorizon(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	waiting(t, d, p, taskID, domain.CostLine{
		Category: domain.CostService, SubjectType: domain.SubjectTool, Amount: "1", Currency: "EUR", Source: "rate",
		Payer: domain.PayerPlatform, Estimate: true, Evidence: map[string]any{"settle": "capture", "hold_id": "old"},
		OccurredAt: time.Now().Add(-8 * 24 * time.Hour),
	})
	if n := settleUntilIdle(t, s); n != 0 || len(bill.captures) != 0 {
		t.Fatalf("a line past the horizon settled (%d)", n)
	}
}

func TestSettleURLEscapesEveryReservedByte(t *testing.T) {
	got, err := settleURL("https://v.test/{a}/x?b={b}", map[string]string{"a": "x/y z~", "b": "é&"})
	if err != nil || got != "https://v.test/x%2Fy%20z~/x?b=%C3%A9%26" {
		t.Fatalf("%q %v", got, err)
	}
	if _, err := settleURL("https://v.test/{missing}", nil); err == nil {
		t.Fatal("a missing parameter filled the URL")
	}
}

// freshDB is a database of its own: the settlement worker claims lines of every workspace.
func freshDB(t *testing.T) db.Database {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	admin, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = admin.Close() }()
	name := "settle_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	if _, err := admin.Exec("CREATE DATABASE " + name); err != nil {
		t.Fatal(err)
	}
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	u.Path = "/" + name
	t.Setenv("AGENTAREA_DB_TEST_URL", u.String())
	return openDB(t)
}

// sameCorrelation: a successor carries its task's correlation, as Python's record() reads it.
func sameCorrelation(t *testing.T, d db.Database, p Principal, taskID string, got *string) bool {
	t.Helper()
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	s, release, err := d.Read(context.Background(), ws)
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	var want *string
	if err := s.Q().QueryRow(context.Background(), `SELECT correlation_id FROM tasks WHERE id = $1`, taskID).Scan(&want); err != nil {
		t.Fatal(err)
	}
	if want == nil || got == nil {
		return want == nil && got == nil
	}
	return *want == *got
}

func captureLine(t *testing.T, d db.Database, p Principal, taskID string, at time.Time) domain.CostLine {
	t.Helper()
	return waiting(t, d, p, taskID, domain.CostLine{
		Category: domain.CostModel, SubjectType: domain.SubjectModelInstance, SubjectID: ptr("gpt-x"), Amount: "1", Currency: "EUR",
		Source: domain.SourceTokenPricing, Payer: domain.PayerPlatform, VendorCost: ptr("0.8"), VendorCurrency: ptr("USD"), Estimate: true,
		Evidence: map[string]any{"settle": "capture", "hold_id": uuid.NewString()}, OccurredAt: at,
	})
}

func (b *settleBilling) captured() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.captures)
}

func batch(t *testing.T, s *Service, at time.Time) int {
	t.Helper()
	n, err := s.SettleBatch(context.Background(), at)
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func TestSettlementHoldsNoTransactionWhileBillingAnswers(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{}
	bill.during = func(req money.CaptureRequest) error {
		return d.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
			_, err := q.Exec(ctx, `SELECT 1 FROM cost_entries WHERE event_id = $1::uuid FOR UPDATE NOWAIT`, req.Metadata["event_id"])
			if err != nil {
				t.Errorf("the line is still locked while billing is asked: %v", err)
			}
			return nil
		})
	}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	captureLine(t, d, p, taskID, time.Now())
	if n := batch(t, s, time.Now()); n != 1 || bill.captured() != 1 {
		t.Fatalf("settled %d, captured %d", n, bill.captured())
	}
}

func TestADeadWorkersClaimExpires(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	base := time.Now().Truncate(40 * time.Second)
	captureLine(t, d, p, taskID, base)
	if lines, err := s.claimSettlement(context.Background(), base, uuid.New()); err != nil || len(lines) != 1 {
		t.Fatalf("claimed %d lines: %v", len(lines), err)
	}
	if n := batch(t, s, base.Add(time.Second)); n != 0 || bill.captured() != 0 {
		t.Fatalf("a line another worker holds was settled (%d)", n)
	}
	if n := batch(t, s, base.Add(settleLease+time.Second)); n != 1 || bill.captured() != 1 {
		t.Fatalf("the dead worker's line was not settled after its claim expired: %d", n)
	}
}

func TestALineBillingRejectsIsDead(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{captureErr: fmt.Errorf("%w: vendor currency '' is not an ISO 4217 code", money.ErrBillingRejected)}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	at := time.Now()
	captureLine(t, d, p, taskID, at)
	batch(t, s, at.Add(-time.Hour))
	batch(t, s, at.Add(time.Second))
	if bill.captured() != 1 {
		t.Fatalf("billing was asked %d times for a line it rejected", bill.captured())
	}
	if reason := deadReason(t, d); !strings.Contains(reason, "ISO 4217") {
		t.Fatalf("dead reason %q", reason)
	}
}

func TestAFailedSettlementBacksOff(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	bill := &settleBilling{captureErr: errors.New("billing is down")}
	s := New(Deps{DB: d, Billing: bill, Pricing: eurPricing{}, Log: quiet()})
	at := time.Now().Add(-time.Hour)
	captureLine(t, d, p, taskID, at.Add(time.Hour))
	for _, step := range []struct {
		after time.Duration
		asked int
	}{{0, 1}, {time.Second, 1}, {6 * time.Second, 2}, {12 * time.Second, 2}, {17 * time.Second, 3}} {
		batch(t, s, at.Add(step.after))
		if bill.captured() != step.asked {
			t.Fatalf("after %s billing was asked %d times, want %d", step.after, bill.captured(), step.asked)
		}
	}
}

func TestALineOfAnInvalidWorkspaceIsDead(t *testing.T) {
	d := freshDB(t)
	p, taskID := seed(t, d)
	s := New(Deps{DB: d, Billing: &settleBilling{}, Pricing: eurPricing{}, Log: quiet()})
	at := time.Now()
	line := captureLine(t, d, p, taskID, at)
	if err := d.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, `UPDATE cost_entries SET workspace_id = '' WHERE event_id = $1::uuid`, line.EventID)
		return err
	}); err != nil {
		t.Fatal(err)
	}
	batch(t, s, at.Add(-time.Hour))
	if err := d.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		lines, err := store.Runs{}.ClaimUnsettled(ctx, q, store.SettleClaim{
			Now: at.Add(time.Second), Since: at.Add(-time.Hour), Tick: SettleTick, MaxInterval: settleMaxInterval, Limit: settleBatch,
		})
		if len(lines) != 0 {
			t.Errorf("a line of an invalid workspace is claimed again: %+v", lines)
		}
		return err
	}); err != nil {
		t.Fatal(err)
	}
	if reason := deadReason(t, d); !strings.Contains(reason, "invalid workspace") {
		t.Fatalf("dead reason %q", reason)
	}
}

func deadReason(t *testing.T, d db.Database) string {
	t.Helper()
	var reason string
	if err := d.Global().Write(context.Background(), func(ctx context.Context, q db.Querier) error {
		return q.QueryRow(ctx, `SELECT COALESCE(dead_reason, '') FROM cost_settlement_claims WHERE dead_at IS NOT NULL`).Scan(&reason)
	}); err != nil {
		t.Fatal(err)
	}
	return reason
}
