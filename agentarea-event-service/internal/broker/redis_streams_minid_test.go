package broker

import (
	"testing"
	"time"
)

func TestMinIDIsTheMillisecondsRetentionAgo(t *testing.T) {
	now := time.UnixMilli(1_000_000)
	if got := MinID(now, time.Second); got != "999000-0" {
		t.Fatalf("MinID = %q, want 999000-0", got)
	}
}
