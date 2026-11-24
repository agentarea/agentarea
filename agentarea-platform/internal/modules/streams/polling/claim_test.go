package polling

import (
	"context"
	"errors"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

func TestOneWorkerHoldsASourceAtATime(t *testing.T) {
	srv := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: srv.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	ctx := context.Background()
	a, b := NewRedisClaimer(client, "a"), NewRedisClaimer(client, "b")

	if ok, err := a.TryClaim(ctx, "s1"); !ok || err != nil {
		t.Fatalf("a claim = %v, %v", ok, err)
	}
	if ok, err := b.TryClaim(ctx, "s1"); ok || err != nil {
		t.Fatalf("b took a's claim: %v, %v", ok, err)
	}
	if ok, err := a.TryClaim(ctx, "s1"); !ok || err != nil {
		t.Fatalf("a could not take its own claim back: %v, %v", ok, err)
	}
	if err := b.Renew(ctx, "s1"); !errors.Is(err, ErrClaimLost) {
		t.Fatalf("b renewed a's claim: %v", err)
	}
	if err := b.Release(ctx, "s1"); err != nil {
		t.Fatal(err)
	}
	if err := a.Renew(ctx, "s1"); err != nil {
		t.Fatalf("b's release dropped a's claim: %v", err)
	}
	if err := a.Release(ctx, "s1"); err != nil {
		t.Fatal(err)
	}
	if ok, _ := b.TryClaim(ctx, "s1"); !ok {
		t.Fatal("a released source was not free")
	}
	if got, _ := srv.Get("polling:claim:s1"); got != "b" {
		t.Fatalf("key holds %q", got)
	}
}
