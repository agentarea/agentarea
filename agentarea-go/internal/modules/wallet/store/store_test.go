package store

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_TEST_POSTGRES_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_TEST_POSTGRES_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func workspace(t *testing.T, pool *pgxpool.Pool) db.Session {
	t.Helper()
	id := uuid.NewString()
	slug := "ws-" + id[:8]
	if _, err := pool.Exec(context.Background(),
		`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, slug); err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(id, slug)
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func agent(t *testing.T, pool *pgxpool.Pool, s db.Session) uuid.UUID {
	t.Helper()
	id := uuid.New()
	if _, err := pool.Exec(context.Background(),
		`INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'a', 'active', $2, 'owner', $3)`,
		id, s.Workspace().ID(), "a-"+id.String()[:8]); err != nil {
		t.Fatal(err)
	}
	return id
}

func newWallet(t *testing.T, s db.Session, agentID uuid.UUID, budget, period string) api.Wallet {
	t.Helper()
	w, err := Store{}.CreateWallet(context.Background(), s, uuid.New(), agentID, "owner", domain.New{
		Type: api.TypeX402, X402Config: []byte(`{"network": "eip155:8453"}`), Budget: budget, Period: period,
	}, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	return w
}

// run keeps keys of one test run apart.
var run = uuid.NewString()[:8] + "-"

type rec struct {
	api.Reservation
	status string
}

func record(agentID, key, status, amount string) rec {
	return rec{api.Reservation{
		UserID: "owner", AgentID: agentID, ExecutionID: "exec-1", Protocol: api.ProtocolX402,
		Amount: money.MustParse(amount), Recipient: "0xabc", ToolName: "t", ToolCallID: "c",
		IdempotencyKey: key,
	}, status}
}

func insert(ctx context.Context, s db.Session, walletID uuid.UUID, r rec, at time.Time) (api.Payment, error) {
	return Store{}.InsertPayment(ctx, s, uuid.New(), walletID, r.AgentID, r.status, r.Reservation, at)
}

func TestWalletLifecycleAndIsolation(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	agentID := agent(t, pool, s)
	var st Store

	w := newWallet(t, s, agentID, "5", api.PeriodDaily)
	if w.Budget.String() != "5.000000" || w.Status != api.StatusActive || w.CredentialsRef != nil || w.MPPConfig != nil {
		t.Fatalf("created %+v", w)
	}
	if string(w.X402Config) != `{"network": "eip155:8453"}` {
		t.Fatalf("x402_config %s", w.X402Config)
	}
	if _, err := st.CreateWallet(ctx, s, uuid.New(), agentID, "owner", domain.New{Type: api.TypeX402, Budget: "1", Period: "daily"}, time.Now()); !errors.Is(err, domain.ErrAlreadyExists) {
		t.Fatalf("second wallet for the agent: %v", err)
	}
	if _, ok, err := st.WalletByAgent(ctx, other, agentID); err != nil || ok {
		t.Fatalf("another workspace sees the wallet: %v %v", ok, err)
	}
	got, ok, err := st.WalletByAgent(ctx, s, agentID)
	if err != nil || !ok || got.ID != w.ID {
		t.Fatalf("get %+v %v %v", got, ok, err)
	}

	if _, err := pool.Exec(ctx, `UPDATE agent_wallets SET mpp_config = 'null'::json WHERE id = $1`, w.ID); err != nil {
		t.Fatal(err)
	}
	if got, _, _ = st.WalletByAgent(ctx, s, agentID); got.MPPConfig != nil {
		t.Fatalf("JSON null read as %s, want none", got.MPPConfig)
	}

	before := got.UpdatedAt
	later := time.Now().Add(time.Hour)
	ref := "wallet_creds_" + agentID.String()
	same := "5"
	if u, ok, err := st.UpdateWallet(ctx, s, uuid.MustParse(w.ID), domain.Patch{Budget: &same}, later); err != nil || !ok || !u.UpdatedAt.Equal(before) {
		t.Fatalf("an unchanged budget moved updated_at: %+v %v %v", u, ok, err)
	}
	ten := "10.5"
	disabled := api.StatusDisabled
	u, ok, err := st.UpdateWallet(ctx, s, uuid.MustParse(w.ID), domain.Patch{Budget: &ten, Status: &disabled, CredentialsRef: &ref}, later)
	if err != nil || !ok || u.Budget.String() != "10.500000" || u.Status != api.StatusDisabled || u.CredentialsRef == nil || string(*u.CredentialsRef) != ref {
		t.Fatalf("update %+v %v %v", u, ok, err)
	}
	if !u.UpdatedAt.After(before) {
		t.Fatalf("updated_at %v did not move past %v", u.UpdatedAt, before)
	}
	if _, ok, _ := st.UpdateWallet(ctx, other, uuid.MustParse(w.ID), domain.Patch{Budget: &ten}, later); ok {
		t.Fatal("another workspace updated the wallet")
	}

	if ok, err := st.DeleteWallet(ctx, other, uuid.MustParse(w.ID)); err != nil || ok {
		t.Fatalf("another workspace deleted the wallet: %v %v", ok, err)
	}
	if ok, err := st.DeleteWallet(ctx, s, uuid.MustParse(w.ID)); err != nil || !ok {
		t.Fatalf("delete %v %v", ok, err)
	}
}

func TestSettledPaymentIsUniquePerKey(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	agentID := agent(t, pool, s)
	w := newWallet(t, s, agentID, "5", api.PeriodExecution)
	wid := uuid.MustParse(w.ID)
	var st Store
	a := agentID.String()

	for range 2 {
		if _, err := insert(ctx, s, wid, record(a, run+"k1", api.PaymentFailed, "0.5"), time.Now()); err != nil {
			t.Fatalf("failed attempts under one key repeat: %v", err)
		}
	}
	first, err := insert(ctx, s, wid, record(a, run+"k1", api.PaymentCompleted, "0.5"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := insert(ctx, s, wid, record(a, run+"k1", api.PaymentCompleted, "0.5"), time.Now()); !errors.Is(err, api.ErrAlreadySettled) {
		t.Fatalf("second settlement under one key: %v", err)
	}
	var n int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM payment_records WHERE idempotency_key = $1 AND status = 'completed'`, run+"k1").Scan(&n); err != nil || n != 1 {
		t.Fatalf("completed rows under k1: %d %v", n, err)
	}
	found, ok, err := st.SettledByKey(ctx, s, run+"k1")
	if err != nil || !ok || found.ID != first.ID || found.Amount.String() != "0.500000" {
		t.Fatalf("settled by key %+v %v %v", found, ok, err)
	}
	if _, ok, _ := st.SettledByKey(ctx, workspace(t, pool), run+"k1"); ok {
		t.Fatal("another workspace sees the settlement")
	}
	if _, ok, _ := st.SettledByKey(ctx, s, run+"missing"); ok {
		t.Fatal("unknown key settled")
	}
}

func TestSumsAreExactAndCountOnlySettled(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	agentID := agent(t, pool, s)
	w := newWallet(t, s, agentID, "5", api.PeriodDaily)
	wid := uuid.MustParse(w.ID)
	var st Store
	a := agentID.String()

	if sum, err := st.SumByExecution(ctx, s, a, "exec-1", nil); err != nil || sum.String() != "0" {
		t.Fatalf("empty sum %v %v", sum, err)
	}
	for i := range 10 {
		key := run + "ok-" + string(rune('a'+i))
		if _, err := insert(ctx, s, wid, record(a, key, api.PaymentCompleted, "0.1"), time.Now()); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := insert(ctx, s, wid, record(a, run+"bad", api.PaymentFailed, "9"), time.Now()); err != nil {
		t.Fatal(err)
	}
	other := record(a, run+"other-exec", api.PaymentCompleted, "2")
	other.ExecutionID = "exec-2"
	if _, err := insert(ctx, s, wid, other, time.Now()); err != nil {
		t.Fatal(err)
	}

	if sum, _ := st.SumByExecution(ctx, s, a, "exec-1", nil); sum.String() != "1.000000" {
		t.Fatalf("ten 0.1 payments sum to %s", sum)
	}
	if sum, _ := st.SumSince(ctx, s, a, nil, nil); sum.String() != "3.000000" {
		t.Fatalf("all-time sum %s", sum)
	}
	future := time.Now().Add(time.Hour)
	if _, err := insert(ctx, s, wid, record(a, run+"held", api.PaymentPending, "0.25"), time.Now()); err != nil {
		t.Fatal(err)
	}
	if _, err := insert(ctx, s, wid, record(a, run+"dead", api.PaymentPending, "7"), time.Now().Add(-2*time.Hour)); err != nil {
		t.Fatal(err)
	}
	hour := time.Now().Add(-time.Hour)
	if sum, _ := st.SumByExecution(ctx, s, a, "exec-1", nil); sum.String() != "1.000000" {
		t.Fatalf("settled sum counts a reservation: %s", sum)
	}
	if sum, _ := st.SumByExecution(ctx, s, a, "exec-1", &hour); sum.String() != "1.250000" {
		t.Fatalf("held sum %s", sum)
	}
	if sum, _ := st.SumSince(ctx, s, a, nil, &hour); sum.String() != "3.250000" {
		t.Fatalf("held all-time sum %s", sum)
	}
	if sum, _ := st.SumSince(ctx, s, a, &future, &hour); sum.String() != "0" {
		t.Fatalf("sum since the future %s", sum)
	}
	if sum, _ := st.SumByExecution(ctx, workspace(t, pool), a, "exec-1", &hour); sum.String() != "0" {
		t.Fatalf("another workspace's sum %s", sum)
	}

	var scale int
	if err := pool.QueryRow(ctx, `SELECT numeric_scale FROM information_schema.columns WHERE table_name = 'payment_records' AND column_name = 'amount_usd'`).Scan(&scale); err != nil || scale != 6 {
		t.Fatalf("amount_usd scale %d %v", scale, err)
	}
}

func TestListFiltersOrderAndFilteredCount(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	agentID := agent(t, pool, s)
	w := newWallet(t, s, agentID, "5", api.PeriodExecution)
	wid := uuid.MustParse(w.ID)
	var st Store
	a := agentID.String()

	base := time.Date(2026, 11, 1, 12, 0, 0, 0, time.UTC)
	mpp := record(a, run+"m1", api.PaymentCompleted, "1")
	mpp.Protocol = api.ProtocolMPP
	rows := []struct {
		r rec
		t time.Time
	}{
		{record(a, run+"p1", api.PaymentCompleted, "1"), base},
		{record(a, run+"p2", api.PaymentFailed, "1"), base.Add(time.Hour)},
		{mpp, base.Add(2 * time.Hour)},
	}
	for _, x := range rows {
		if _, err := insert(ctx, s, wid, x.r, x.t); err != nil {
			t.Fatal(err)
		}
	}

	all, err := st.ListPayments(ctx, s, a, domain.PaymentFilter{}, 50, 0)
	if err != nil || len(all) != 3 || all[0].IdempotencyKey != run+"m1" || all[2].IdempotencyKey != run+"p1" {
		t.Fatalf("newest first: %+v %v", all, err)
	}
	page, _ := st.ListPayments(ctx, s, a, domain.PaymentFilter{}, 1, 1)
	if len(page) != 1 || page[0].IdempotencyKey != run+"p2" {
		t.Fatalf("second page %+v", page)
	}
	x402, completed := api.ProtocolX402, api.PaymentCompleted
	from, to := base.Add(30*time.Minute), base.Add(time.Hour)
	for name, tc := range map[string]struct {
		f    domain.PaymentFilter
		want int
	}{
		"protocol":  {domain.PaymentFilter{Protocol: &x402}, 2},
		"status":    {domain.PaymentFilter{Status: &completed}, 2},
		"both":      {domain.PaymentFilter{Protocol: &x402, Status: &completed}, 1},
		"from":      {domain.PaymentFilter{From: &from}, 2},
		"to":        {domain.PaymentFilter{To: &to}, 2},
		"from, to":  {domain.PaymentFilter{From: &from, To: &to}, 1},
		"no filter": {domain.PaymentFilter{}, 3},
	} {
		got, err := st.ListPayments(ctx, s, a, tc.f, 50, 0)
		if err != nil || len(got) != tc.want {
			t.Fatalf("%s: %d rows, want %d (%v)", name, len(got), tc.want, err)
		}
		if n, err := st.CountPayments(ctx, s, a, tc.f); err != nil || n != tc.want {
			t.Fatalf("%s: count %d, want %d (%v)", name, n, tc.want, err)
		}
	}
	if got, _ := st.ListPayments(ctx, workspace(t, pool), a, domain.PaymentFilter{}, 50, 0); len(got) != 0 {
		t.Fatal("another workspace lists the payments")
	}
}

func TestExhaustedSelection(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var st Store
	now := time.Now().UTC()
	daily, _ := domain.PeriodStart(api.PeriodDaily, now)
	monthly, _ := domain.PeriodStart(api.PeriodMonthly, now)

	mkStatus := func(budget, period, spend, status string, at time.Time) uuid.UUID {
		a := agent(t, pool, s)
		w := newWallet(t, s, a, budget, period)
		if spend != "" {
			if _, err := insert(ctx, s, uuid.MustParse(w.ID), record(a.String(), uuid.NewString(), status, spend), at); err != nil {
				t.Fatal(err)
			}
		}
		return a
	}
	mk := func(budget, period, spend string, at time.Time) uuid.UUID {
		return mkStatus(budget, period, spend, api.PaymentCompleted, at)
	}
	hit := mk("1", api.PeriodDaily, "1", now)
	held := mkStatus("1", api.PeriodDaily, "1", api.PaymentPending, now)
	_ = mkStatus("1", api.PeriodDaily, "1", api.PaymentFailed, now)
	monthlyHit := mk("2", api.PeriodMonthly, "3", monthly.Add(time.Minute))
	_ = mk("1", api.PeriodDaily, "0.5", now)
	_ = mk("1", api.PeriodDaily, "1", daily.Add(-time.Minute))
	_ = mk("0", api.PeriodDaily, "", now)
	_ = mk("1", api.PeriodExecution, "5", now)
	disabled := mk("1", api.PeriodDaily, "1", now)
	if _, err := pool.Exec(ctx, `UPDATE agent_wallets SET status = 'disabled' WHERE agent_id = $1`, disabled); err != nil {
		t.Fatal(err)
	}

	_ = mkStatus("1", api.PeriodDaily, "1", api.PaymentPending, now.Add(-2*time.Hour))
	got, err := st.Exhausted(ctx, s, daily, monthly, now.Add(-time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	ids := map[string]bool{}
	for _, w := range got {
		ids[w.AgentID] = true
	}
	if len(got) != 3 || !ids[hit.String()] || !ids[monthlyHit.String()] || !ids[held.String()] {
		t.Fatalf("exhausted %+v", got)
	}
	if got, _ := st.Exhausted(ctx, workspace(t, pool), daily, monthly, now.Add(-time.Hour)); len(got) != 0 {
		t.Fatal("another workspace's wallets listed")
	}
}

func TestDeletingTheWalletDeletesItsPayments(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	agentID := agent(t, pool, s)
	w := newWallet(t, s, agentID, "5", api.PeriodExecution)
	var st Store
	if _, err := insert(ctx, s, uuid.MustParse(w.ID), record(agentID.String(), run+"k", api.PaymentCompleted, "1"), time.Now()); err != nil {
		t.Fatal(err)
	}
	if ok, err := st.DeleteWallet(ctx, s, uuid.MustParse(w.ID)); err != nil || !ok {
		t.Fatal(ok, err)
	}
	if n, _ := st.CountPayments(ctx, s, agentID.String(), domain.PaymentFilter{}); n != 0 {
		t.Fatalf("%d payments outlived the wallet", n)
	}
}

func TestSettledKeyIsUniquePerWorkspace(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	var st Store
	key := run + "shared"
	for range 2 {
		s := workspace(t, pool)
		agentID := agent(t, pool, s)
		w := newWallet(t, s, agentID, "5", api.PeriodExecution)
		if _, err := insert(ctx, s, uuid.MustParse(w.ID), record(agentID.String(), key, api.PaymentCompleted, "0.5"), time.Now()); err != nil {
			t.Fatalf("a settlement in another workspace blocks this one: %v", err)
		}
		if _, ok, err := st.SettledByKey(ctx, s, key); err != nil || !ok {
			t.Fatalf("settled by key %v %v", ok, err)
		}
	}
}

func TestReservationSettlesOnce(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	agentID := agent(t, pool, s)
	w := newWallet(t, s, agentID, "5", api.PeriodExecution)
	wid := uuid.MustParse(w.ID)
	var st Store
	a := agentID.String()
	key := run + "reserve"

	meta := []byte(`{"network": "base"}`)
	r := record(a, key, api.PaymentPending, "0.5")
	r.ProtocolMetadata = meta
	held, err := insert(ctx, s, wid, r, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if got, ok, err := st.PendingByKey(ctx, s, key, time.Now().Add(-time.Minute)); err != nil || !ok || got.ID != held.ID {
		t.Fatalf("pending by key %+v %v %v", got, ok, err)
	}
	if _, ok, _ := st.PendingByKey(ctx, s, key, time.Now().Add(time.Minute)); ok {
		t.Fatal("an expired hold is still held")
	}
	if _, ok, _ := st.PendingByKey(ctx, workspace(t, pool), key, time.Now().Add(-time.Minute)); ok {
		t.Fatal("another workspace sees the reservation")
	}
	if _, ok, _ := st.Settle(ctx, workspace(t, pool), uuid.MustParse(held.ID), api.PaymentCompleted, api.Settlement{}, time.Now()); ok {
		t.Fatal("another workspace settled the reservation")
	}
	tx := "0xtx"
	done, ok, err := st.Settle(ctx, s, uuid.MustParse(held.ID), api.PaymentCompleted, api.Settlement{TxHash: &tx}, time.Now())
	if err != nil || !ok || done.Status != api.PaymentCompleted || *done.TxHash != tx || string(done.ProtocolMetadata) != string(meta) {
		t.Fatalf("settle %+v %v %v", done, ok, err)
	}
	if _, ok, err := st.Settle(ctx, s, uuid.MustParse(held.ID), api.PaymentFailed, api.Settlement{}, time.Now()); ok || err != nil {
		t.Fatalf("settled twice: %v %v", ok, err)
	}
	second, err := insert(ctx, s, wid, record(a, key, api.PaymentPending, "0.5"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := st.Settle(ctx, s, uuid.MustParse(second.ID), api.PaymentCompleted, api.Settlement{}, time.Now()); !errors.Is(err, api.ErrAlreadySettled) {
		t.Fatalf("second completion under one key: %v", err)
	}
	if got, ok, err := st.LockWallet(ctx, s, agentID); err != nil || !ok || got.ID != w.ID {
		t.Fatalf("lock wallet %+v %v %v", got, ok, err)
	}
}
