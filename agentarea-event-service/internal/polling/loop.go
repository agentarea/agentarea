package polling

import (
	"context"
	"log/slog"
	"time"
)

// backoffDurations defines the retry wait sequence: 1s, 2s, 4s, then cap at 30s.
var backoffDurations = []time.Duration{
	1 * time.Second,
	2 * time.Second,
	4 * time.Second,
	30 * time.Second,
}

// backoffWait returns the wait duration for the given attempt index (0-based).
func backoffWait(attempt int) time.Duration {
	if attempt < 0 {
		return backoffDurations[0]
	}
	if attempt >= len(backoffDurations) {
		return backoffDurations[len(backoffDurations)-1]
	}
	return backoffDurations[attempt]
}

// PollFunc is the function called on each poll iteration.
// It should return an error if polling failed; a nil error resets the backoff counter.
type PollFunc func(ctx context.Context) error

// RunLoop executes fn repeatedly until ctx is cancelled.
// On error it backs off before retrying. On panic it recovers and restarts with backoff.
func RunLoop(ctx context.Context, triggerID string, fn PollFunc) {
	attempts := 0
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		func() {
			defer func() {
				if r := recover(); r != nil {
					slog.Error("panic in poll loop, recovering",
						"trigger_id", triggerID,
						"panic", r,
					)
				}
			}()

			if err := fn(ctx); err != nil {
				if ctx.Err() != nil {
					return
				}
				wait := backoffWait(attempts)
				slog.Warn("poll error, backing off",
					"trigger_id", triggerID,
					"error", err,
					"backoff", wait,
				)
				attempts++
				select {
				case <-ctx.Done():
				case <-time.After(wait):
				}
				return
			}
			// Successful poll — reset backoff
			attempts = 0
		}()
	}
}
