//go:build suite

package harness

import (
	"testing"
	"time"
)

// PollInterval is the pause between two attempts of Eventually.
const PollInterval = 250 * time.Millisecond

// Eventually retries cond until it returns nil, failing the test with the
// last error once within has passed.
func Eventually(t testing.TB, within time.Duration, cond func() error) {
	t.Helper()
	deadline := time.Now().Add(within)
	for {
		err := cond()
		if err == nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("not reached within %s: %v", within, err)
		}
		time.Sleep(PollInterval)
	}
}

// Never checks cond keeps returning nil for the whole period: for "this must
// not happen" assertions (a run that must stay paused, a row that must not appear).
func Never(t testing.TB, period time.Duration, cond func() error) {
	t.Helper()
	deadline := time.Now().Add(period)
	for time.Now().Before(deadline) {
		if err := cond(); err != nil {
			t.Fatalf("broke within %s: %v", period, err)
		}
		time.Sleep(PollInterval)
	}
}
