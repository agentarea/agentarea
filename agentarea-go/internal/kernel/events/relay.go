package events

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"slices"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// OutboxHandler performs a row instead of publishing it, on the relay's
// transaction in the row's workspace. Delivery is at least once and it never
// gives up, so it must be idempotent.
type OutboxHandler func(ctx context.Context, s db.Session, e Envelope) error

// RelayOptions are outbox_relay.py's constructor defaults when zero.
type RelayOptions struct {
	Interval    time.Duration // 1s
	BatchSize   int           // 100
	MaxAttempts int           // 10
	Handlers    map[string]OutboxHandler
	RetryBase   time.Duration // 1s
	RetryCap    time.Duration // 300s
	AlertAfter  int           // 20
	Now         func() time.Time
}

// outboxSource is the CloudEvents source of what the relay publishes (domain_events.py).
const outboxSource = "agentarea-outbox"

// Relay drains event_outbox (outbox_relay.py): one transaction per batch
// holds its rows FOR UPDATE SKIP LOCKED, so any number of relays share the
// table; each row is published to domain.events.<type>, or performed by its
// handler, then marked. A publish failure counts an attempt and the row is
// left alone after MaxAttempts; a handler failure retries with exponential
// backoff forever. A crash after publishing redelivers the batch: readers
// dedup by event id.
type Relay struct {
	database db.Database
	pub      Publisher
	log      *slog.Logger
	o        RelayOptions
}

// NewRelay builds a relay; pub publishes to the topic it is given.
func NewRelay(database db.Database, pub Publisher, log *slog.Logger, o RelayOptions) *Relay {
	if o.Interval <= 0 {
		o.Interval = time.Second
	}
	if o.BatchSize <= 0 {
		o.BatchSize = 100
	}
	if o.MaxAttempts <= 0 {
		o.MaxAttempts = 10
	}
	if o.RetryBase <= 0 {
		o.RetryBase = time.Second
	}
	if o.RetryCap <= 0 {
		o.RetryCap = 300 * time.Second
	}
	if o.AlertAfter <= 0 {
		o.AlertAfter = 20
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	return &Relay{database: database, pub: pub, log: log, o: o}
}

// Run processes a batch every Interval until ctx ends; a failed batch is
// logged and the next pass tries again.
func (r *Relay) Run(ctx context.Context) error {
	for {
		if _, err := r.ProcessBatch(ctx); err != nil && ctx.Err() == nil {
			r.log.ErrorContext(ctx, "OutboxRelay batch failed", "error", err)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(r.o.Interval):
		}
	}
}

type outboxRow struct {
	id, eventID, eventType, workspaceID string
	payload                             []byte
	attempts                            int
}

// ProcessBatch publishes one batch and returns how many rows it published.
func (r *Relay) ProcessBatch(ctx context.Context) (int, error) {
	published := 0
	err := r.database.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		now := r.o.Now().UTC().Truncate(time.Microsecond)
		rows, err := r.fetch(ctx, q, now)
		if err != nil {
			return err
		}
		for _, row := range rows {
			handler := r.o.Handlers[row.eventType]
			err := r.deliver(ctx, q, row, handler)
			switch {
			case err == nil:
				if _, err := q.Exec(ctx, `UPDATE event_outbox SET published_at = $2, updated_at = $3 WHERE id = $1`,
					row.id, r.o.Now().UTC().Truncate(time.Microsecond), time.Now().UTC().Truncate(time.Microsecond)); err != nil {
					return err
				}
				published++
			case handler != nil:
				if err := r.retryLater(ctx, q, row, err, now); err != nil {
					return err
				}
			default:
				r.log.ErrorContext(ctx, "OutboxRelay failed to publish event",
					"event_id", row.eventID, "event_type", row.eventType, "error", err)
				if err := r.markFailed(ctx, q, row.id, err, nil); err != nil {
					return err
				}
				if row.attempts+1 >= r.o.MaxAttempts {
					r.log.ErrorContext(ctx, "OutboxRelay giving up on event",
						"event_id", row.eventID, "event_type", row.eventType, "attempts", row.attempts+1, "error", err)
				}
			}
		}
		return nil
	})
	if err != nil {
		return 0, err
	}
	return published, nil
}

func (r *Relay) fetch(ctx context.Context, q db.Querier, now time.Time) ([]outboxRow, error) {
	unbounded := slices.Sorted(maps.Keys(r.o.Handlers))
	if unbounded == nil {
		unbounded = []string{}
	}
	rs, err := q.Query(ctx, `SELECT id::text, event_id::text, event_type, workspace_id, payload::text, attempts
		FROM event_outbox
		WHERE published_at IS NULL
		  AND (next_attempt_at IS NULL OR next_attempt_at <= $1)
		  AND (attempts < $2 OR event_type = ANY($3::text[]))
		ORDER BY created_at ASC
		LIMIT $4
		FOR UPDATE SKIP LOCKED`, now, r.o.MaxAttempts, unbounded, r.o.BatchSize)
	if err != nil {
		return nil, fmt.Errorf("fetch outbox: %w", err)
	}
	defer rs.Close()
	var out []outboxRow
	for rs.Next() {
		var row outboxRow
		var payload string
		if err := rs.Scan(&row.id, &row.eventID, &row.eventType, &row.workspaceID, &payload, &row.attempts); err != nil {
			return nil, fmt.Errorf("fetch outbox: %w", err)
		}
		row.payload = []byte(payload)
		out = append(out, row)
	}
	return out, rs.Err()
}

func (r *Relay) deliver(ctx context.Context, q db.Querier, row outboxRow, handler OutboxHandler) error {
	env, err := ParseEnvelope(row.payload)
	if err != nil {
		return err
	}
	if handler == nil {
		return r.pub.Publish(ctx, DomainEvent(env), DomainEventsTopic(env.EventType))
	}
	ws, err := scope.NewWorkspace(row.workspaceID, "")
	if err != nil {
		return err
	}
	// A savepoint keeps a failed handler's statements from aborting the batch.
	if _, err := q.Exec(ctx, "SAVEPOINT outbox_handler"); err != nil {
		return err
	}
	if herr := handler(ctx, db.NewTxSession(ws, q), env); herr != nil {
		if _, err := q.Exec(ctx, "ROLLBACK TO SAVEPOINT outbox_handler"); err != nil {
			return errors.Join(herr, err)
		}
		return herr
	}
	_, err = q.Exec(ctx, "RELEASE SAVEPOINT outbox_handler")
	return err
}

// DomainEvent is the integration event the relay publishes for an outbox
// envelope: same id and time, subject from data's aggregate_id.
func DomainEvent(env Envelope) IntegrationEvent {
	e := IntegrationEvent{
		ID: env.EventID, Type: env.EventType, Source: outboxSource, Time: env.Timestamp,
		SpecVersion: defaultSpecVersion, DataContentType: defaultDataContentType,
		Data: dataOrEmpty(env.Data), Extensions: map[string]string{},
	}
	if s, ok := pyTruthyStr(env.Data["aggregate_id"]); ok {
		e.Subject = s
	}
	return e
}

func (r *Relay) markFailed(ctx context.Context, q db.Querier, id string, cause error, retryAt *time.Time) error {
	_, err := q.Exec(ctx, `UPDATE event_outbox
		SET attempts = attempts + 1, last_error = $2, next_attempt_at = $3, updated_at = $4
		WHERE id = $1`, id, cause.Error(), retryAt, time.Now().UTC().Truncate(time.Microsecond))
	return err
}

func (r *Relay) retryLater(ctx context.Context, q db.Querier, row outboxRow, cause error, now time.Time) error {
	attempts := row.attempts + 1
	delay := min(r.o.RetryBase<<min(attempts-1, 30), r.o.RetryCap)
	if delay <= 0 {
		delay = r.o.RetryCap
	}
	at := now.Add(delay)
	if err := r.markFailed(ctx, q, row.id, cause, &at); err != nil {
		return err
	}
	if attempts == r.o.AlertAfter {
		r.log.ErrorContext(ctx, "OutboxRelay still failing; retrying until it succeeds",
			"event_id", row.eventID, "event_type", row.eventType, "attempts", attempts, "retry_every", r.o.RetryCap, "error", cause)
		return nil
	}
	r.log.WarnContext(ctx, "OutboxRelay handler failed; retrying",
		"event_id", row.eventID, "event_type", row.eventType, "attempts", attempts, "retry_in", delay, "error", cause)
	return nil
}
