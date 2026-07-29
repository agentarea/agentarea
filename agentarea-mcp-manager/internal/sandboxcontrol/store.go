package sandboxcontrol

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	redis "github.com/go-redis/redis/v8"
)

type Store interface {
	CreateExecution(ctx context.Context, record *ExecutionRecord) error
	GetExecution(ctx context.Context, id string) (*ExecutionRecord, error)
	UpdateExecution(ctx context.Context, record *ExecutionRecord) error
}

type RedisStore struct {
	client *redis.Client
	prefix string
	ttl    time.Duration
}

func NewRedisStore(redisURL, prefix string, ttl time.Duration) (*RedisStore, error) {
	opts, err := parseRedisOptions(redisURL)
	if err != nil {
		return nil, err
	}
	if prefix == "" {
		prefix = "agentarea:sandbox"
	}
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	return &RedisStore{
		client: redis.NewClient(opts),
		prefix: prefix,
		ttl:    ttl,
	}, nil
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

func (s *RedisStore) CreateExecution(ctx context.Context, record *ExecutionRecord) error {
	return s.write(ctx, record)
}

func (s *RedisStore) UpdateExecution(ctx context.Context, record *ExecutionRecord) error {
	return s.write(ctx, record)
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
	if err := validateExecutionRecord(&record); err != nil {
		return nil, fmt.Errorf("invalid sandbox execution %s in Redis: %w", id, err)
	}
	return &record, nil
}

func (s *RedisStore) write(ctx context.Context, record *ExecutionRecord) error {
	if record == nil || record.ID == "" {
		return fmt.Errorf("execution record id is required")
	}
	if err := validateExecutionRecord(record); err != nil {
		return fmt.Errorf("invalid sandbox execution %s: %w", record.ID, err)
	}
	if record.Result != nil && (record.Result.Stdout != "" || record.Result.Stderr != "") {
		return fmt.Errorf("execution output bodies cannot be persisted in Redis")
	}
	data, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("encode sandbox execution %s: %w", record.ID, err)
	}
	if err := s.client.Set(ctx, s.key(record.ID), data, s.ttl).Err(); err != nil {
		return fmt.Errorf("write sandbox execution %s: %w", record.ID, err)
	}
	return nil
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
