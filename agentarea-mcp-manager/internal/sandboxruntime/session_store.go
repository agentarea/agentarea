package sandboxruntime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	redis "github.com/go-redis/redis/v8"
	"github.com/google/uuid"
)

type SessionStore struct {
	client *redis.Client
	prefix string
	ttl    time.Duration
}

func NewSessionStore(client *redis.Client, prefix string, ttl time.Duration) (*SessionStore, error) {
	if client == nil {
		return nil, fmt.Errorf("sandbox session store requires Redis")
	}
	if prefix == "" {
		prefix = "agentarea:sandbox"
	}
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	return &SessionStore{client: client, prefix: prefix, ttl: ttl}, nil
}

func (s *SessionStore) Get(ctx context.Context, provider, taskID string) (*Session, error) {
	data, err := s.client.Get(ctx, s.sessionKey(provider, taskID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, ErrSessionNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get sandbox session: %w", err)
	}
	var session Session
	if err := json.Unmarshal(data, &session); err != nil {
		return nil, fmt.Errorf("decode sandbox session: %w", err)
	}
	if session.Provider != provider || session.TaskID != taskID || session.ID == "" {
		return nil, fmt.Errorf("stored sandbox session identity is invalid")
	}
	return &session, nil
}

func (s *SessionStore) Put(ctx context.Context, session *Session) error {
	if session == nil || session.Provider == "" || session.TaskID == "" || session.ID == "" {
		return fmt.Errorf("sandbox session identity is required")
	}
	data, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("encode sandbox session: %w", err)
	}
	if err := s.client.Set(ctx, s.sessionKey(session.Provider, session.TaskID), data, s.ttl).Err(); err != nil {
		return fmt.Errorf("store sandbox session: %w", err)
	}
	return nil
}

func (s *SessionStore) Touch(ctx context.Context, provider, taskID string) error {
	ok, err := s.client.Expire(ctx, s.sessionKey(provider, taskID), s.ttl).Result()
	if err != nil {
		return fmt.Errorf("renew sandbox session record: %w", err)
	}
	if !ok {
		return ErrSessionNotFound
	}
	return nil
}

func (s *SessionStore) Delete(ctx context.Context, provider, taskID string) error {
	if err := s.client.Del(ctx, s.sessionKey(provider, taskID)).Err(); err != nil {
		return fmt.Errorf("delete sandbox session: %w", err)
	}
	return nil
}

// DeleteIfSession removes only the exact record the caller observed. A stale
// request must never delete a replacement session created concurrently.
func (s *SessionStore) DeleteIfSession(ctx context.Context, session *Session) error {
	if session == nil {
		return fmt.Errorf("sandbox session is required")
	}
	data, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("encode sandbox session for compare-and-delete: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) == ARGV[1] then return redis.call("DEL", KEYS[1]) else return 0 end`
	if err := s.client.Eval(ctx, script, []string{s.sessionKey(session.Provider, session.TaskID)}, data).Err(); err != nil {
		return fmt.Errorf("compare-and-delete sandbox session: %w", err)
	}
	return nil
}

// WithCreationLock serializes first use of one task across the API process
// (which may stage files) and the runner process (which executes commands).
func (s *SessionStore) WithCreationLock(ctx context.Context, provider, taskID string, fn func() error) error {
	key := s.lockKey(provider, taskID)
	token := uuid.NewString()
	for {
		acquired, err := s.client.SetNX(ctx, key, token, 10*time.Minute).Result()
		if err != nil {
			return fmt.Errorf("acquire sandbox creation lock: %w", err)
		}
		if acquired {
			defer s.releaseLock(context.Background(), key, token)
			return fn()
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(50 * time.Millisecond):
		}
	}
}

func (s *SessionStore) releaseLock(ctx context.Context, key, token string) {
	const script = `if redis.call("GET", KEYS[1]) == ARGV[1] then return redis.call("DEL", KEYS[1]) else return 0 end`
	_ = s.client.Eval(ctx, script, []string{key}, token).Err()
}

func (s *SessionStore) sessionKey(provider, taskID string) string {
	return s.prefix + ":provider-session:" + provider + ":" + taskID
}

func (s *SessionStore) lockKey(provider, taskID string) string {
	return s.prefix + ":provider-session-lock:" + provider + ":" + taskID
}
