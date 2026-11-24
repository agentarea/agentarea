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
	tg := TelegramLive{Redis: rdb, LockTTL: 90 * time.Millisecond}
	release, err := tg.lock(context.Background(), "t1")
	if err != nil {
		t.Fatal(err)
	}
	for range 10 {
		mr.FastForward(60 * time.Millisecond)
		time.Sleep(40 * time.Millisecond)
	}
	if !mr.Exists(telegramLockPrefix + "t1") {
		t.Fatal("the lock lapsed while its send was still running")
	}
	release()
	if mr.Exists(telegramLockPrefix + "t1") {
		t.Fatal("a released lock is still held")
	}
	if err := mr.Set(telegramLockPrefix+"t2", "someone-else"); err != nil {
		t.Fatal(err)
	}
	busy, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	if _, err := (TelegramLive{Redis: rdb, LockTTL: 90 * time.Millisecond}).lock(busy, "t2"); err == nil {
		t.Fatal("a held lock was taken")
	}
}
