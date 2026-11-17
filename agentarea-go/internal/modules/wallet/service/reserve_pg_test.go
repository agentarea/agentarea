package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openPools(t *testing.T) *db.Pools {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatal(err)
	}
	password, _ := u.User.Password()
	p, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: u.Path[1:], User: u.User.Username(), Password: password,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 40, PoolTimeout: 10 * time.Second,
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(p.Close)
	return p
}

func pgService(t *testing.T) (*Service, *db.Pools, scope.Workspace, uuid.UUID) {
	t.Helper()
	pools := openPools(t)
	ctx := context.Background()
	wsID := uuid.NewString()
	agent := uuid.New()
	if err := pools.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		if _, err := q.Exec(ctx, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, wsID, "ws-"+wsID[:8]); err != nil {
			return err
		}
		_, err := q.Exec(ctx, `INSERT INTO agents (id, name, status, workspace_id, created_by, slug) VALUES ($1, 'a', 'active', $2, 'owner', $3)`,
			agent, wsID, "a-"+agent.String()[:8])
		return err
	}); err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(wsID, "ws-"+wsID[:8])
	if err != nil {
		t.Fatal(err)
	}
	s := New(Deps{DB: pools, Store: store.Store{}, Agents: fakeAgents{}, Secrets: fakeSecrets{&world{secrets: map[string]string{}}}, Log: slog.New(slog.DiscardHandler)})
	return s, pools, ws, agent
}

func TestParallelPaymentsNeverExceedTheBudget(t *testing.T) {
	s, _, ws, agent := pgService(t)
	ctx := context.Background()
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("1"), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	const n = 24
	amount := money.MustParse("0.25")
	start := make(chan struct{})
	var wg sync.WaitGroup
	errs := make(chan error, n)
	for i := range n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			p, err := s.Reserve(ctx, ws, api.Reservation{UserID: "u", AgentID: agent.String(), ExecutionID: "e1", Protocol: api.ProtocolX402,
				Amount: amount, Recipient: "0xabc", ToolName: "t", ToolCallID: fmt.Sprint("c", i), IdempotencyKey: uuid.NewString()})
			if errors.Is(err, api.ErrBudgetExceeded) {
				return
			}
			if err != nil {
				errs <- err
				return
			}
			time.Sleep(5 * time.Millisecond)
			if _, err := s.Complete(ctx, ws, p.ID, api.Settlement{}); err != nil {
				errs <- err
			}
		}()
	}
	close(start)
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatal(err)
	}
	b, err := s.Balance(ctx, ws, agent.String())
	if err != nil {
		t.Fatal(err)
	}
	if b.Spent.String() != "1.000000" || b.Remaining.String() != "0" {
		t.Fatalf("%d parallel payments spent %s of a budget of 1, %s left", n, b.Spent, b.Remaining)
	}
}

func TestASignedHoldIsReturnedAgainUntilItSettles(t *testing.T) {
	s, _, ws, agent := pgService(t)
	ctx := context.Background()
	now := time.Now().UTC()
	s.d.Now = func() time.Time { return now }
	if _, err := s.Create(ctx, ws, "u", agent, Create{Type: api.TypeX402, X402Config: []byte(x402), Budget: money.MustParse("1"), Period: api.PeriodExecution}); err != nil {
		t.Fatal(err)
	}
	reserve := func(key string) api.Payment {
		t.Helper()
		p, err := s.Reserve(ctx, ws, api.Reservation{UserID: "u", AgentID: agent.String(), ExecutionID: "e1", Protocol: api.ProtocolX402,
			Amount: money.MustParse("0.25"), Recipient: "0xabc", ToolName: "t", ToolCallID: "c", IdempotencyKey: key})
		if err != nil {
			t.Fatal(err)
		}
		return p
	}
	hold := reserve("signed")
	if hold.Signed != nil {
		t.Fatalf("a new hold carries a payment: %v", hold.Signed)
	}
	first, err := s.Sign(ctx, ws, hold.ID, http.Header{"Payment-Signature": {"sig-1"}})
	if err != nil || first.Signed.Get("Payment-Signature") != "sig-1" {
		t.Fatalf("sign: %+v %v", first.Signed, err)
	}
	again, err := s.Sign(ctx, ws, hold.ID, http.Header{"Payment-Signature": {"sig-2"}})
	if err != nil || again.Signed.Get("Payment-Signature") != "sig-1" {
		t.Fatalf("a second signature replaced the first: %+v %v", again.Signed, err)
	}
	unsigned := reserve("unsigned")

	now = now.Add(api.ReservationHold + time.Minute)
	if got := reserve("signed"); got.ID != hold.ID || got.Signed.Get("Payment-Signature") != "sig-1" {
		t.Fatalf("an expired signed hold was not returned: %+v", got)
	}
	if got := reserve("unsigned"); got.ID == unsigned.ID || got.Signed != nil {
		t.Fatalf("an expired unsigned hold was returned: %+v", got)
	}
	if _, err := s.Complete(ctx, ws, hold.ID, api.Settlement{}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Sign(ctx, ws, hold.ID, http.Header{"Payment-Signature": {"sig-3"}}); !errors.Is(err, api.ErrNotReserved) {
		t.Fatalf("signed a settled payment: %v", err)
	}
}
