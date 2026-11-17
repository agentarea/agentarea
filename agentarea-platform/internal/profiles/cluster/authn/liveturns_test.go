package authn

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"

	port "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

func TestLiveTurnsOnValkey(t *testing.T) {
	url := os.Getenv("AGENTAREA_REDIS_TEST_URL")
	if url == "" {
		t.Skip("AGENTAREA_REDIS_TEST_URL is not set")
	}
	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatal(err)
	}
	rdb := redis.NewClient(opts)
	t.Cleanup(func() { _ = rdb.Close() })
	ctx := context.Background()
	live := NewLiveTurns(rdb)
	turnID := "authn-test-" + time.Now().Format("150405.000000")

	if err := live.Begin(ctx, turnID, 1500*time.Millisecond); err != nil {
		t.Fatal(err)
	}
	if v, err := rdb.Get(ctx, "runners:live-turn:"+turnID).Result(); err != nil || v != "1" {
		t.Fatalf("Python reads runners:live-turn:<id> = 1: %q %v", v, err)
	}
	if ttl := rdb.TTL(ctx, "runners:live-turn:"+turnID).Val(); ttl <= 0 || ttl > time.Second {
		t.Fatalf("ttl %s, want whole seconds", ttl)
	}
	if err := live.Begin(ctx, turnID, 500*time.Millisecond); err == nil {
		t.Fatal("a sub-second ttl would write a key that never expires")
	}

	w := newWorld(t)
	gate := newTestGate(t, Config{Issuer: testIssuer, Audience: testAudience, GatewaySecret: testSecret},
		Deps{Store: w.store, Graph: w.graph, LiveTurns: live})
	tokens, err := NewTurnTokens(testSecret, nil)
	if err != nil {
		t.Fatal(err)
	}
	c := turnClaims(port.SubjectUser, "u1", "u1", "ws-own")
	c.TurnID = turnID
	token, err := tokens.Issue(c, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := gate.Verify(ctx, token); err != nil {
		t.Fatalf("live turn: %v", err)
	}
	if err := live.End(ctx, turnID); err != nil {
		t.Fatal(err)
	}
	_, err = gate.Verify(ctx, token)
	wantRefusal(t, err, 401, port.DetailTurnEnded)
}
