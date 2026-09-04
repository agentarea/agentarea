package sandboxcontrol

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"
)

type Store interface {
	// CreateExecution atomically persists the queued aggregate and appends its
	// requested event. A runner must never observe one without the other.
	CreateExecution(ctx context.Context, record *ExecutionRecord) error
	GetExecution(ctx context.Context, id string) (*ExecutionRecord, error)
	// UpdateExecution atomically compares the current revision, persists the
	// next aggregate revision, and appends its lifecycle event.
	UpdateExecution(ctx context.Context, expectedRevision int64, record *ExecutionRecord, eventType string) error
}

type RedisStore struct {
	client        *redis.Client
	prefix        string
	ttl           time.Duration
	policy        ExecutionPolicy
	requestStream string
	eventStream   string
	eventSource   string
}

type RedisStoreOption func(*RedisStore)

func WithEventStreams(requestStream, eventStream, source string) RedisStoreOption {
	return func(store *RedisStore) {
		if requestStream != "" {
			store.requestStream = requestStream
		}
		if eventStream != "" {
			store.eventStream = eventStream
		}
		if source != "" {
			store.eventSource = source
		}
	}
}

func NewRedisStore(redisURL, prefix string, ttl time.Duration, policy ExecutionPolicy, options ...RedisStoreOption) (*RedisStore, error) {
	opts, err := parseRedisOptions(redisURL)
	if err != nil {
		return nil, err
	}
	if prefix == "" {
		prefix = "agentarea:sandbox"
	}
	if ttl <= 0 {
		return nil, fmt.Errorf("sandbox execution record TTL must be positive")
	}
	if err := policy.Validate(); err != nil {
		return nil, err
	}
	store := &RedisStore{
		client:        redis.NewClient(opts),
		prefix:        prefix,
		ttl:           ttl,
		policy:        policy,
		requestStream: DefaultExecutionRequestStream,
		eventStream:   DefaultExecutionEventStream,
		eventSource:   "agentarea.mcp-manager.sandbox-control",
	}
	for _, option := range options {
		if option != nil {
			option(store)
		}
	}
	return store, nil
}

func (s *RedisStore) Close() error {
	if s == nil || s.client == nil {
		return nil
	}
	return s.client.Close()
}

func (s *RedisStore) RedisClient() *redis.Client {
	if s == nil {
		return nil
	}
	return s.client
}

func (s *RedisStore) MaxExecutionTimeoutSeconds() int {
	if s == nil {
		return 0
	}
	return s.policy.MaxTimeoutSeconds
}

func (s *RedisStore) ExecutionPolicy() ExecutionPolicy {
	if s == nil {
		return ExecutionPolicy{}
	}
	return s.policy
}

func (s *RedisStore) CreateExecution(ctx context.Context, record *ExecutionRecord) error {
	data, payload, err := s.encodeTransition(record, EventTypeExecutionRequested)
	if err != nil {
		return err
	}
	key := s.key(record.ID)
	err = s.client.Watch(ctx, func(tx *redis.Tx) error {
		if _, getErr := tx.Get(ctx, key).Result(); getErr == nil {
			return ErrExecutionConflict
		} else if !errors.Is(getErr, redis.Nil) {
			return getErr
		}
		_, pipeErr := tx.TxPipelined(ctx, func(pipe redis.Pipeliner) error {
			pipe.Set(ctx, key, data, s.ttl)
			pipe.XAdd(ctx, &redis.XAddArgs{Stream: s.requestStream, Values: map[string]any{"event": payload}})
			pipe.Publish(ctx, s.requestStream, payload)
			return nil
		})
		return pipeErr
	}, key)
	return transactionError("create", record.ID, err)
}

func (s *RedisStore) UpdateExecution(ctx context.Context, expectedRevision int64, record *ExecutionRecord, eventType string) error {
	if expectedRevision <= 0 || record == nil || record.Revision != expectedRevision+1 {
		return fmt.Errorf("%w: invalid expected/next revision", ErrExecutionConflict)
	}
	data, payload, err := s.encodeTransition(record, eventType)
	if err != nil {
		return err
	}
	key := s.key(record.ID)
	err = s.client.Watch(ctx, func(tx *redis.Tx) error {
		currentData, getErr := tx.Get(ctx, key).Bytes()
		if errors.Is(getErr, redis.Nil) {
			return ErrExecutionNotFound
		}
		if getErr != nil {
			return getErr
		}
		var current ExecutionRecord
		if decodeErr := json.Unmarshal(currentData, &current); decodeErr != nil {
			return fmt.Errorf("decode current sandbox execution: %w", decodeErr)
		}
		if current.Revision != expectedRevision {
			return ErrExecutionConflict
		}
		_, pipeErr := tx.TxPipelined(ctx, func(pipe redis.Pipeliner) error {
			pipe.Set(ctx, key, data, s.ttl)
			pipe.XAdd(ctx, &redis.XAddArgs{Stream: s.eventStream, Values: map[string]any{"event": payload}})
			pipe.Publish(ctx, s.eventStream, payload)
			return nil
		})
		return pipeErr
	}, key)
	return transactionError("update", record.ID, err)
}

func (s *RedisStore) GetExecution(ctx context.Context, id string) (*ExecutionRecord, error) {
	if err := validateExecutionID(id); err != nil {
		return nil, err
	}
	data, err := s.client.Get(ctx, s.key(id)).Bytes()
	if err == redis.Nil {
		return nil, ErrExecutionNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get sandbox execution %s: %w", id, err)
	}
	var record ExecutionRecord
	if err := json.Unmarshal(data, &record); err != nil {
		return nil, fmt.Errorf("decode sandbox execution %s: %w", id, err)
	}
	if err := validateExecutionRecord(&record, s.policy.MaxTimeoutSeconds); err != nil {
		return nil, fmt.Errorf("invalid sandbox execution %s in Redis: %w", id, err)
	}
	return &record, nil
}

func (s *RedisStore) encodeTransition(record *ExecutionRecord, eventType string) ([]byte, string, error) {
	if record == nil || record.ID == "" {
		return nil, "", fmt.Errorf("execution record id is required")
	}
	if err := validateExecutionRecord(record, s.policy.MaxTimeoutSeconds); err != nil {
		return nil, "", fmt.Errorf("invalid sandbox execution %s: %w", record.ID, err)
	}
	if record.Result != nil && (record.Result.Stdout != "" || record.Result.Stderr != "") {
		return nil, "", fmt.Errorf("execution output bodies cannot be persisted in Redis")
	}
	data, err := json.Marshal(record)
	if err != nil {
		return nil, "", fmt.Errorf("encode sandbox execution %s: %w", record.ID, err)
	}
	payload, err := marshalExecutionCloudEvent(record, eventType, s.eventSource)
	if err != nil {
		return nil, "", err
	}
	return data, payload, nil
}

func transactionError(operation, id string, err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, redis.TxFailedErr) || errors.Is(err, ErrExecutionConflict) {
		return fmt.Errorf("%w: %s %s", ErrExecutionConflict, operation, id)
	}
	if errors.Is(err, ErrExecutionNotFound) {
		return ErrExecutionNotFound
	}
	return fmt.Errorf("%s sandbox execution %s transaction: %w", operation, id, err)
}

func (s *RedisStore) key(id string) string {
	return s.prefix + ":execution:" + id
}

func parseRedisOptions(redisURL string) (*redis.Options, error) {
	if parsed, err := redis.ParseURL(redisURL); err == nil {
		return parsed, nil
	}
	addr := redisURL
	if cutAddr, found := strings.CutPrefix(redisURL, "redis://"); found {
		addr = cutAddr
	}
	if addr == "" {
		addr = "localhost:6379"
	}
	return &redis.Options{Addr: addr}, nil
}
