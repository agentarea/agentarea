package replies

import (
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
)

func TestTheTaskLockLastsAsLongAsItsSend(t *testing.T) {
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = rdb.Close() })
	ticks, renewed := make(chan time.Time), make(chan struct{})
	tg := TelegramLive{Redis: rdb, LockTTL: 90 * time.Millisecond, renewals: ticks, renewed: renewed}
	release, err := tg.lock(context.Background(), "t1")
	if err != nil {
		t.Fatal(err)
	}
	for range 10 {
		mr.FastForward(60 * time.Millisecond)
		ticks <- time.Time{}
		<-renewed
	}
	if !mr.Exists(telegramLockPrefix + "t1") {
		t.Fatal("the lock lapsed while its send was still running")
	}
	release()
	if mr.Exists(telegramLockPrefix + "t1") {
		t.Fatal("a released lock is still held")
	}

	held, _ := TelegramLive{Redis: rdb, LockTTL: 90 * time.Millisecond, renewals: make(chan time.Time)}.lock(context.Background(), "t3")
	mr.FastForward(100 * time.Millisecond)
	if mr.Exists(telegramLockPrefix + "t3") {
		t.Fatal("a lock nobody renews outlived its TTL")
	}
	held()

	if err := mr.Set(telegramLockPrefix+"t2", "someone-else"); err != nil {
		t.Fatal(err)
	}
	busy, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	if _, err := (TelegramLive{Redis: rdb, LockTTL: 90 * time.Millisecond}).lock(busy, "t2"); err == nil {
		t.Fatal("a held lock was taken")
	}
}
