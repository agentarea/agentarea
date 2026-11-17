package polling

import (
	"context"
	"log/slog"
	"time"
)

// backoffWait is the wait after the attempt-th failure in a row (0-based): 1s, 2s, 4s, then 30s.
func backoffWait(attempt int) time.Duration {
	waits := [...]time.Duration{time.Second, 2 * time.Second, 4 * time.Second, 30 * time.Second}
	return waits[max(0, min(attempt, len(waits)-1))]
}

// PollFunc is the function called on each poll iteration.
// It should return an error if polling failed; a nil error resets the backoff counter.
type PollFunc func(ctx context.Context) error

// RunLoop executes fn repeatedly until ctx is cancelled.
// On error it backs off before retrying. On panic it recovers and restarts with backoff.
func RunLoop(ctx context.Context, log *slog.Logger, sourceID string, fn PollFunc) {
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
					log.ErrorContext(ctx, "panic in poll loop, recovering",
						"source_id", sourceID,
						"panic", r,
					)
				}
			}()

			if err := fn(ctx); err != nil {
				if ctx.Err() != nil {
					return
				}
				wait := backoffWait(attempts)
				log.WarnContext(ctx, "poll error, backing off",
					"source_id", sourceID,
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
