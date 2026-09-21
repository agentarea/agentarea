package usage

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/google/uuid"
)

func testRedis(t *testing.T) *redis.Client {
	t.Helper()
	url := os.Getenv("USAGE_TEST_REDIS_URL")
	if url == "" {
		if os.Getenv("USAGE_REQUIRE_REDIS") != "" {
			t.Fatal("USAGE_REQUIRE_REDIS is set but USAGE_TEST_REDIS_URL is missing")
		}
		t.Skip("USAGE_TEST_REDIS_URL not set; requires real Redis")
	}
	options, err := redis.ParseURL(url)
	if err != nil {
		t.Fatal(err)
	}
	client := redis.NewClient(options)
	t.Cleanup(func() { _ = client.Close() })
	return client
}

type streamRecorderFunc func(context.Context, Event) error

func (f streamRecorderFunc) Record(ctx context.Context, event Event) error {
	return f(ctx, event)
}

func testUsageStream(t *testing.T, client *redis.Client) string {
	t.Helper()
	stream := "usage-test:" + uuid.NewString()
	t.Cleanup(func() {
		keys, err := client.Keys(context.Background(), stream+"*").Result()
		if err != nil {
			t.Error(err)
		} else if len(keys) > 0 {
			if err := client.Del(context.Background(), keys...).Err(); err != nil {
				t.Error(err)
			}
		}
	})
	return stream
}

func runTestUsageConsumer(t *testing.T, consumer *Consumer) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- consumer.Run(ctx) }()
	t.Cleanup(func() {
		cancel()
		if err := awaitUsageResult(t, done); err != nil && !errors.Is(err, context.Canceled) {
			t.Errorf("consumer exit: %v", err)
		}
	})
}

func awaitUsageResult(t *testing.T, result <-chan error) error {
	t.Helper()
	select {
	case err := <-result:
		return err
	case <-time.After(5 * time.Second):
		t.Fatal("usage operation did not complete")
		return nil
	}
}

func assertUsageUnacknowledged(t *testing.T, client *redis.Client, stream string, event Event, result <-chan error) {
	t.Helper()
	select {
	case err := <-result:
		t.Fatalf("publisher returned before durable commit: %v", err)
	default:
	}
	data, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	if exists, err := client.Exists(context.Background(), commitAckKey(stream, data)).Result(); err != nil || exists != 0 {
		t.Fatalf("uncommitted fact has success acknowledgement: exists=%d err=%v", exists, err)
	}
	pending, err := client.XPending(context.Background(), stream, consumerGroup).Result()
	if err != nil || pending.Count < 1 {
		t.Fatalf("uncommitted fact not retained pending: pending=%v err=%v", pending, err)
	}
}

func assertStoredUsageFact(t *testing.T, store *Store, event Event) {
	t.Helper()
	var count int
	var data string
	if err := store.db.QueryRowContext(context.Background(), `SELECT count(*),min(data::text)
		FROM resource_usage_events WHERE source=$1 AND event_id=$2`, event.Source, event.ID).Scan(&count, &data); err != nil {
		t.Fatal(err)
	}
	var counters map[string]json.RawMessage
	if err := json.Unmarshal([]byte(data), &counters); err != nil {
		t.Fatal(err)
	}
	if count != 1 || string(counters["cpu_usage_ns"]) != "18446744073709551615" || string(counters["memory_usage_bytes"]) != "9007199254740993" {
		t.Fatalf("replay or Redis transport altered raw fact: count=%d data=%s", count, data)
	}
}

func TestPublisherWaitsForCommitAndReplaysExactEvent(t *testing.T) {
	store := openTestStore(t)
	client := testRedis(t)
	stream := testUsageStream(t, client)
	publisher := NewPublisher(client)
	publisher.stream = stream
	entered := make(chan error, 1)
	release := make(chan struct{})
	consumer := NewConsumer(client, streamRecorderFunc(func(ctx context.Context, event Event) error {
		select {
		case entered <- nil:
		default:
		}
		select {
		case <-release:
			return store.Record(ctx, event)
		case <-ctx.Done():
			return ctx.Err()
		}
	}), nil)
	consumer.stream = stream
	runTestUsageConsumer(t, consumer)
	event := testEvent()
	result := make(chan error, 1)
	go func() { result <- publisher.Record(context.Background(), event) }()
	if err := awaitUsageResult(t, entered); err != nil {
		t.Fatal(err)
	}
	assertUsageUnacknowledged(t, client, stream, event, result)
	close(release)
	if err := awaitUsageResult(t, result); err != nil {
		t.Fatal(err)
	}
	assertStoredUsageFact(t, store, event)
	if err := publisher.Record(context.Background(), event); err != nil {
		t.Fatalf("exact replay rejected: %v", err)
	}
	assertStoredUsageFact(t, store, event)
	data, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	if ttl, err := client.PTTL(context.Background(), commitAckKey(stream, data)).Result(); err != nil || ttl <= 0 || ttl > commitAckTTL {
		t.Fatalf("commit acknowledgement must expire: ttl=%v err=%v", ttl, err)
	}
}

func TestPublisherCancellationLeavesBlockedFactPending(t *testing.T) {
	store := openTestStore(t)
	client := testRedis(t)
	stream := testUsageStream(t, client)
	publisher := NewPublisher(client)
	publisher.stream = stream
	entered := make(chan error, 1)
	release := make(chan struct{})
	consumer := NewConsumer(client, streamRecorderFunc(func(ctx context.Context, event Event) error {
		entered <- nil
		select {
		case <-release:
			return store.Record(ctx, event)
		case <-ctx.Done():
			return ctx.Err()
		}
	}), nil)
	consumer.stream = stream
	runTestUsageConsumer(t, consumer)
	event := testEvent()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() { result <- publisher.Record(ctx, event) }()
	if err := awaitUsageResult(t, entered); err != nil {
		t.Fatal(err)
	}
	assertUsageUnacknowledged(t, client, stream, event, result)
	cancel()
	if err := awaitUsageResult(t, result); !errors.Is(err, context.Canceled) {
		t.Fatalf("canceled publisher returned %v", err)
	}
	assertUsageUnacknowledged(t, client, stream, event, result)
}

func TestConsumerRetainsUncommittedFactForRetry(t *testing.T) {
	store := openTestStore(t)
	client := testRedis(t)
	ctx := context.Background()
	stream := testUsageStream(t, client)
	publisher := NewPublisher(client)
	publisher.stream = stream
	// A closed real SQL connection forces the production write to fail.
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	attempted := make(chan error, 1)
	failedConsumer := NewConsumer(client, streamRecorderFunc(func(ctx context.Context, event Event) error {
		err := store.Record(ctx, event)
		attempted <- err
		return err
	}), nil)
	failedConsumer.stream = stream
	runTestUsageConsumer(t, failedConsumer)
	event := testEvent()
	publishCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	result := make(chan error, 1)
	go func() { result <- publisher.Record(publishCtx, event) }()
	if err := awaitUsageResult(t, attempted); err == nil {
		t.Fatal("closed PostgreSQL store accepted event")
	}
	assertUsageUnacknowledged(t, client, stream, event, result)
	cancel()
	if err := awaitUsageResult(t, result); !errors.Is(err, context.Canceled) {
		t.Fatalf("uncommitted publisher returned %v", err)
	}
	if count, err := client.XLen(ctx, stream).Result(); err != nil || count != 1 {
		t.Fatalf("uncommitted fact deleted: count=%d err=%v", count, err)
	}
	recoveredStore := openTestStore(t)
	recoveredConsumer := NewConsumer(client, recoveredStore, nil)
	recoveredConsumer.stream = stream
	recoveredConsumer.claimIdle = 0
	if _, err := recoveredConsumer.reclaim(ctx, "-"); err != nil {
		t.Fatal(err)
	}
	assertStoredUsageFact(t, recoveredStore, event)
	if count, err := client.XLen(ctx, stream).Result(); err != nil || count != 0 {
		t.Fatalf("persisted fact not removed from stream: count=%d err=%v", count, err)
	}
	data, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	if ack, err := client.Get(ctx, commitAckKey(stream, data)).Result(); err != nil || ack != "1" {
		t.Fatalf("recovered commit not acknowledged: ack=%q err=%v", ack, err)
	}
}

func TestPublisherCollisionCannotInheritCommitAcknowledgement(t *testing.T) {
	store := openTestStore(t)
	client := testRedis(t)
	stream := testUsageStream(t, client)
	publisher := NewPublisher(client)
	publisher.stream = stream
	attempted := make(chan error, 1)
	consumer := NewConsumer(client, streamRecorderFunc(func(ctx context.Context, event Event) error {
		err := store.Record(ctx, event)
		attempted <- err
		return err
	}), nil)
	consumer.stream = stream
	runTestUsageConsumer(t, consumer)
	event := testEvent()
	if err := publisher.Record(context.Background(), event); err != nil {
		t.Fatal(err)
	}
	if err := awaitUsageResult(t, attempted); err != nil {
		t.Fatal(err)
	}
	for _, change := range []struct {
		name   string
		mutate func(*Event)
	}{
		{"counter", func(e *Event) { e.Data = json.RawMessage(`{"cpu_usage_ns":18446744073709551614}`) }},
		{"timestamp", func(e *Event) { e.OccurredAt = e.OccurredAt.Add(time.Nanosecond) }},
		{"workspace", func(e *Event) { e.WorkspaceID = uuid.NewString() }},
	} {
		t.Run(change.name, func(t *testing.T) {
			collision := event
			change.mutate(&collision)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			result := make(chan error, 1)
			go func() { result <- publisher.Record(ctx, collision) }()
			if err := awaitUsageResult(t, attempted); !errors.Is(err, ErrIdentityCollision) {
				t.Fatalf("changed envelope not rejected: %v", err)
			}
			assertUsageUnacknowledged(t, client, stream, collision, result)
			cancel()
			if err := awaitUsageResult(t, result); !errors.Is(err, context.Canceled) {
				t.Fatalf("conflicting publisher returned %v", err)
			}
		})
	}
	assertStoredUsageFact(t, store, event)
	pending, err := client.XPending(context.Background(), stream, consumerGroup).Result()
	if err != nil || pending.Count != 3 {
		t.Fatalf("conflicting facts not retained: pending=%v err=%v", pending, err)
	}
}

func TestConsumerReclaimsDuplicateAndLeavesPoisonPending(t *testing.T) {
	store := openTestStore(t)
	client := testRedis(t)
	ctx := context.Background()
	stream := testUsageStream(t, client)
	consumer := NewConsumer(client, store, nil)
	consumer.stream = stream
	consumer.claimIdle = 0
	if err := client.XGroupCreateMkStream(ctx, stream, consumerGroup, "0").Err(); err != nil {
		t.Fatal(err)
	}
	event := testEvent()
	data, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	// Seed deliveries directly to simulate a publisher and consumer dying
	// after commit but before Redis acknowledgement.
	for range 2 {
		if err := client.XAdd(ctx, &redis.XAddArgs{
			Stream: stream, Values: map[string]any{"event": string(data)},
		}).Err(); err != nil {
			t.Fatal(err)
		}
	}
	poisonID, err := client.XAdd(ctx, &redis.XAddArgs{
		Stream: stream, Values: map[string]any{"event": "not-json"},
	}).Result()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group: consumerGroup, Consumer: "terminated-consumer", Streams: []string{stream, ">"}, Count: 3,
	}).Result(); err != nil {
		t.Fatal(err)
	}
	if err := store.Record(ctx, event); err != nil {
		t.Fatal(err)
	}
	if _, err := consumer.reclaim(ctx, "-"); err != nil {
		t.Fatal(err)
	}
	messages, rangeErr := client.XRange(ctx, stream, "-", "+").Result()
	pending, pendingErr := client.XPendingExt(ctx, &redis.XPendingExtArgs{
		Stream: stream, Group: consumerGroup, Start: "-", End: "+", Count: 100,
	}).Result()
	if rangeErr != nil || pendingErr != nil || len(messages) != 1 || messages[0].ID != poisonID || len(pending) != 1 || pending[0].ID != poisonID {
		t.Fatalf("committed replay not reclaimed or poison lost: stream=%v pending=%v errors=%v/%v", messages, pending, rangeErr, pendingErr)
	}
	if exists, err := client.Exists(ctx, commitAckKey(stream, []byte("not-json"))).Result(); err != nil || exists != 0 {
		t.Fatalf("poison event acknowledged: exists=%d err=%v", exists, err)
	}
	assertStoredUsageFact(t, store, event)
}
