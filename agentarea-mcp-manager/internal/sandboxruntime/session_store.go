package sandboxruntime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"time"

	redis "github.com/go-redis/redis/v8"
	"github.com/google/uuid"
)

type SessionStore struct {
	client *redis.Client
	prefix string
	ttl    time.Duration
}

type hydrationRecord struct {
	SessionID   string `json:"session_id"`
	WorkspaceID string `json:"workspace_id"`
	Revision    string `json:"revision"`
}

type taskLock struct {
	key   string
	token string
}

const (
	distributedFenceTTL          = 30 * time.Second
	distributedFencePollInterval = 50 * time.Millisecond
)

func NewSessionStore(client *redis.Client, prefix string, ttl time.Duration) (*SessionStore, error) {
	if client == nil {
		return nil, fmt.Errorf("sandbox session store requires Redis")
	}
	if prefix == "" {
		prefix = "agentarea:sandbox"
	}
	if ttl <= 0 {
		return nil, fmt.Errorf("sandbox session store TTL must be positive")
	}
	return &SessionStore{client: client, prefix: prefix, ttl: ttl}, nil
}

func (s *SessionStore) Get(ctx context.Context, provider, workspaceID, taskID string) (*Session, error) {
	if _, err := s.client.Get(ctx, s.quarantineKey(provider, workspaceID, taskID)).Bytes(); err == nil {
		return nil, ErrSessionQuarantined
	} else if !errors.Is(err, redis.Nil) {
		return nil, fmt.Errorf("get sandbox quarantine: %w", err)
	}
	data, err := s.client.Get(ctx, s.sessionKey(provider, workspaceID, taskID)).Bytes()
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
	if session.Provider != provider || session.WorkspaceID != workspaceID || session.TaskID != taskID || session.ID == "" {
		return nil, fmt.Errorf("stored sandbox session identity is invalid")
	}
	return &session, nil
}

func (s *SessionStore) GetQuarantined(ctx context.Context, provider, workspaceID, taskID string) (*Session, error) {
	data, err := s.client.Get(ctx, s.quarantineKey(provider, workspaceID, taskID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, ErrSessionNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get quarantined sandbox session: %w", err)
	}
	var session Session
	if err := json.Unmarshal(data, &session); err != nil {
		return nil, fmt.Errorf("decode quarantined sandbox session: %w", err)
	}
	if session.Provider != provider || session.WorkspaceID != workspaceID || session.TaskID != taskID || session.ID == "" {
		return nil, fmt.Errorf("quarantined sandbox session identity is invalid")
	}
	return &session, nil
}

func (s *SessionStore) Put(ctx context.Context, session *Session) error {
	if session == nil || session.Provider == "" || session.WorkspaceID == "" || session.TaskID == "" || session.ID == "" {
		return fmt.Errorf("sandbox session identity is required")
	}
	data, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("encode sandbox session: %w", err)
	}
	if err := s.client.Set(ctx, s.sessionKey(session.Provider, session.WorkspaceID, session.TaskID), data, s.ttl).Err(); err != nil {
		return fmt.Errorf("store sandbox session: %w", err)
	}
	return nil
}

func validateProvisioningIntent(intent ProvisioningIntent) error {
	return intent.validate(intent.Provider)
}

func (s *SessionStore) getProvisioning(
	ctx context.Context,
	provider, workspaceID, taskID string,
) (*ProvisioningIntent, error) {
	data, err := s.client.Get(ctx, s.provisioningKey(provider, workspaceID, taskID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, ErrSessionNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get sandbox provisioning intent: %w", err)
	}
	var intent ProvisioningIntent
	if err := json.Unmarshal(data, &intent); err != nil {
		return nil, fmt.Errorf("decode sandbox provisioning intent: %w", err)
	}
	if err := validateProvisioningIntent(intent); err != nil {
		return nil, err
	}
	if intent.Provider != provider || intent.WorkspaceID != workspaceID || intent.TaskID != taskID {
		return nil, fmt.Errorf("stored sandbox provisioning intent identity is invalid")
	}
	return &intent, nil
}

// beginProvisioningIfLockOwned persists ownership before the remote create
// request. A session, quarantine, or earlier unresolved intent all block a new
// allocation for the same task.
func (s *SessionStore) beginProvisioningIfLockOwned(
	ctx context.Context,
	intent ProvisioningIntent,
	lock taskLock,
) error {
	if err := validateProvisioningIntent(intent); err != nil {
		return err
	}
	if lock.key == "" || lock.token == "" {
		return fmt.Errorf("sandbox creation lock identity is required")
	}
	data, err := json.Marshal(intent)
	if err != nil {
		return fmt.Errorf("encode sandbox provisioning intent: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end; if redis.call("EXISTS", KEYS[2]) ~= 0 or redis.call("EXISTS", KEYS[3]) ~= 0 or redis.call("EXISTS", KEYS[4]) ~= 0 then return -1 end; redis.call("SET", KEYS[4], ARGV[2], "PX", ARGV[3]); return 1`
	committed, err := s.client.Eval(
		ctx,
		script,
		[]string{
			lock.key,
			s.sessionKey(intent.Provider, intent.WorkspaceID, intent.TaskID),
			s.quarantineKey(intent.Provider, intent.WorkspaceID, intent.TaskID),
			s.provisioningKey(intent.Provider, intent.WorkspaceID, intent.TaskID),
		},
		lock.token,
		data,
		s.ttl.Milliseconds(),
	).Int64()
	if err != nil {
		return fmt.Errorf("record sandbox provisioning intent: %w", err)
	}
	switch committed {
	case 1:
		return nil
	case -1:
		return fmt.Errorf("sandbox task already has a binding or unresolved provisioning")
	default:
		return fmt.Errorf("sandbox creation lock ownership was lost before provisioning")
	}
}

func (s *SessionStore) putProvisioningIfLockOwned(
	ctx context.Context,
	session *Session,
	intent ProvisioningIntent,
	lock taskLock,
) error {
	if session == nil || session.Provider == "" || session.WorkspaceID == "" || session.TaskID == "" || session.ID == "" {
		return fmt.Errorf("sandbox session identity is required")
	}
	if err := validateProvisioningIntent(intent); err != nil {
		return err
	}
	if lock.key == "" || lock.token == "" {
		return fmt.Errorf("sandbox creation lock identity is required")
	}
	sessionData, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("encode sandbox session: %w", err)
	}
	intentData, err := json.Marshal(intent)
	if err != nil {
		return fmt.Errorf("encode sandbox provisioning intent: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) ~= ARGV[1] or redis.call("GET", KEYS[2]) ~= ARGV[2] then return 0 end; if redis.call("EXISTS", KEYS[3]) ~= 0 or redis.call("EXISTS", KEYS[4]) ~= 0 then return -1 end; redis.call("SET", KEYS[3], ARGV[3], "PX", ARGV[4]); redis.call("DEL", KEYS[2]); return 1`
	committed, err := s.client.Eval(
		ctx,
		script,
		[]string{
			lock.key,
			s.provisioningKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.sessionKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.quarantineKey(session.Provider, session.WorkspaceID, session.TaskID),
		},
		lock.token,
		intentData,
		sessionData,
		s.ttl.Milliseconds(),
	).Int64()
	if err != nil {
		return fmt.Errorf("commit provisioned sandbox session: %w", err)
	}
	switch committed {
	case 1:
		return nil
	case -1:
		return fmt.Errorf("sandbox binding changed during provisioning commit")
	default:
		return fmt.Errorf("sandbox creation lock ownership was lost before commit")
	}
}

// quarantineProvisioningIfLockOwned records ownership of a provider resource
// that failed validation before it could become a usable binding. The creation
// lock prevents a concurrent replacement, while the tombstone survives a
// failed compensating delete and gives retirement a concrete session to retry.
func (s *SessionStore) quarantineProvisioningIfLockOwned(
	ctx context.Context,
	session *Session,
	intent ProvisioningIntent,
	lock taskLock,
) error {
	if session == nil || session.Provider == "" || session.WorkspaceID == "" || session.TaskID == "" || session.ID == "" {
		return fmt.Errorf("sandbox provisioning identity is required")
	}
	if lock.key == "" || lock.token == "" {
		return fmt.Errorf("sandbox creation lock identity is required")
	}
	if err := validateProvisioningIntent(intent); err != nil {
		return err
	}
	sessionData, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("encode failed sandbox provisioning: %w", err)
	}
	intentData, err := json.Marshal(intent)
	if err != nil {
		return fmt.Errorf("encode sandbox provisioning intent: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) ~= ARGV[1] or redis.call("GET", KEYS[2]) ~= ARGV[2] then return 0 end; if redis.call("EXISTS", KEYS[3]) ~= 0 or redis.call("EXISTS", KEYS[4]) ~= 0 then return -1 end; redis.call("SET", KEYS[4], ARGV[3], "PX", ARGV[4]); redis.call("DEL", KEYS[2], KEYS[5]); return 1`
	committed, err := s.client.Eval(
		ctx,
		script,
		[]string{
			lock.key,
			s.provisioningKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.sessionKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.quarantineKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.hydrationKey(session.Provider, session.WorkspaceID, session.TaskID),
		},
		lock.token,
		intentData,
		sessionData,
		s.ttl.Milliseconds(),
	).Int64()
	if err != nil {
		return fmt.Errorf("record failed sandbox provisioning: %w", err)
	}
	switch committed {
	case 1:
		return nil
	case -1:
		return fmt.Errorf("sandbox binding changed during failed provisioning")
	default:
		return fmt.Errorf("sandbox creation lock ownership was lost before failed provisioning was recorded")
	}
}

func (s *SessionStore) clearProvisioningIfLockOwned(
	ctx context.Context,
	intent ProvisioningIntent,
	lock taskLock,
) error {
	if err := validateProvisioningIntent(intent); err != nil {
		return err
	}
	if lock.key == "" || lock.token == "" {
		return fmt.Errorf("sandbox creation lock identity is required")
	}
	data, err := json.Marshal(intent)
	if err != nil {
		return fmt.Errorf("encode sandbox provisioning intent: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end; if redis.call("GET", KEYS[2]) ~= ARGV[2] then return -1 end; redis.call("DEL", KEYS[2]); return 1`
	cleared, err := s.client.Eval(
		ctx,
		script,
		[]string{lock.key, s.provisioningKey(intent.Provider, intent.WorkspaceID, intent.TaskID)},
		lock.token,
		data,
	).Int64()
	if err != nil {
		return fmt.Errorf("clear sandbox provisioning intent: %w", err)
	}
	switch cleared {
	case 1:
		return nil
	case -1:
		return fmt.Errorf("sandbox provisioning intent changed before cleanup")
	default:
		return fmt.Errorf("sandbox creation lock ownership was lost before provisioning cleanup")
	}
}

func (s *SessionStore) Touch(ctx context.Context, provider, workspaceID, taskID string) error {
	ok, err := s.client.Expire(ctx, s.sessionKey(provider, workspaceID, taskID), s.ttl).Result()
	if err != nil {
		return fmt.Errorf("renew sandbox session record: %w", err)
	}
	if !ok {
		return ErrSessionNotFound
	}
	return nil
}

func (s *SessionStore) Delete(ctx context.Context, provider, workspaceID, taskID string) error {
	if err := s.client.Del(ctx, s.sessionKey(provider, workspaceID, taskID), s.hydrationKey(provider, workspaceID, taskID)).Err(); err != nil {
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
	const script = `if redis.call("GET", KEYS[1]) == ARGV[1] then return redis.call("DEL", KEYS[1], KEYS[2]) else return 0 end`
	if err := s.client.Eval(ctx, script, []string{s.sessionKey(session.Provider, session.WorkspaceID, session.TaskID), s.hydrationKey(session.Provider, session.WorkspaceID, session.TaskID)}, data).Err(); err != nil {
		return fmt.Errorf("compare-and-delete sandbox session: %w", err)
	}
	return nil
}

// QuarantineIfSession atomically makes the exact observed binding unavailable
// before provider cleanup starts. If cleanup cannot complete, the tombstone
// remains and ensure() fails closed instead of creating a replacement beside an
// orphan that still contains task data.
func (s *SessionStore) QuarantineIfSession(ctx context.Context, session *Session) (bool, error) {
	if session == nil {
		return false, fmt.Errorf("sandbox session is required")
	}
	data, err := json.Marshal(session)
	if err != nil {
		return false, fmt.Errorf("encode sandbox session for quarantine: %w", err)
	}
	const script = `local quarantined = redis.call("GET", KEYS[3]); if quarantined == ARGV[1] then return 1 end; if redis.call("GET", KEYS[1]) == ARGV[1] then redis.call("SET", KEYS[3], ARGV[1], "PX", ARGV[2]); redis.call("DEL", KEYS[1], KEYS[2]); return 1 else return 0 end`
	quarantined, err := s.client.Eval(
		ctx,
		script,
		[]string{
			s.sessionKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.hydrationKey(session.Provider, session.WorkspaceID, session.TaskID),
			s.quarantineKey(session.Provider, session.WorkspaceID, session.TaskID),
		},
		data,
		s.ttl.Milliseconds(),
	).Int64()
	if err != nil {
		return false, fmt.Errorf("quarantine sandbox session: %w", err)
	}
	return quarantined == 1, nil
}

func (s *SessionStore) ClearQuarantineIfSession(ctx context.Context, session *Session) error {
	if session == nil {
		return fmt.Errorf("sandbox session is required")
	}
	data, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("encode sandbox session for quarantine cleanup: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) == ARGV[1] then return redis.call("DEL", KEYS[1]) else return 0 end`
	if err := s.client.Eval(
		ctx,
		script,
		[]string{s.quarantineKey(session.Provider, session.WorkspaceID, session.TaskID)},
		data,
	).Err(); err != nil {
		return fmt.Errorf("clear sandbox quarantine: %w", err)
	}
	return nil
}

// WithCreationLock serializes first use of one task across the API process
// (which may stage files) and the runner process (which executes commands).
func (s *SessionStore) WithCreationLock(
	ctx context.Context,
	provider, workspaceID, taskID string,
	fn func(context.Context, taskLock) error,
) error {
	return s.withTaskLock(ctx, provider, workspaceID, taskID, "binding", fn)
}

// acquireOperationFence serializes one provider binding across every manager
// and runner process that shares this store. A retirement intent blocks new
// operations before it waits for the current holder, preserving writer
// priority instead of letting a polling operation starve cleanup indefinitely.
func (s *SessionStore) acquireOperationFence(
	ctx context.Context,
	provider, workspaceID, taskID string,
) (context.Context, func(), error) {
	operationKey := s.lockKey(provider, workspaceID, taskID, "operation")
	retirementKey := s.lockKey(provider, workspaceID, taskID, "retirement-intent")
	token := uuid.NewString()
	const acquireScript = `if redis.call("EXISTS", KEYS[2]) == 0 and redis.call("EXISTS", KEYS[1]) == 0 then redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2]); return 1 else return 0 end`
	for {
		acquired, err := s.client.Eval(
			ctx,
			acquireScript,
			[]string{operationKey, retirementKey},
			token,
			distributedFenceTTL.Milliseconds(),
		).Int64()
		if err != nil {
			return nil, nil, fmt.Errorf("acquire sandbox operation fence: %w", err)
		}
		if acquired == 1 {
			return s.startFenceLease(ctx, token, operationKey)
		}
		if err := waitForFenceRetry(ctx); err != nil {
			return nil, nil, err
		}
	}
}

// acquireRetirementFence publishes intent before waiting for the active
// operation. New operations observe that marker atomically and cannot overtake
// cleanup. Both keys are renewable and token-owned, so a stale process cannot
// release a successor's fence.
func (s *SessionStore) acquireRetirementFence(
	ctx context.Context,
	provider, workspaceID, taskID string,
) (context.Context, func(), error) {
	operationKey := s.lockKey(provider, workspaceID, taskID, "operation")
	retirementKey := s.lockKey(provider, workspaceID, taskID, "retirement-intent")
	token := uuid.NewString()
	for {
		acquired, err := s.client.SetNX(ctx, retirementKey, token, distributedFenceTTL).Result()
		if err != nil {
			return nil, nil, fmt.Errorf("acquire sandbox retirement intent: %w", err)
		}
		if acquired {
			break
		}
		if err := waitForFenceRetry(ctx); err != nil {
			return nil, nil, err
		}
	}

	releaseIntent := func() { s.releaseFenceKeys(context.Background(), token, retirementKey) }
	nextRenewal := time.Now().Add(distributedFenceTTL / 3)
	const acquireOperationScript = `if redis.call("GET", KEYS[2]) == ARGV[1] and redis.call("EXISTS", KEYS[1]) == 0 then redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2]); return 1 else return 0 end`
	for {
		acquired, err := s.client.Eval(
			ctx,
			acquireOperationScript,
			[]string{operationKey, retirementKey},
			token,
			distributedFenceTTL.Milliseconds(),
		).Int64()
		if err != nil {
			releaseIntent()
			return nil, nil, fmt.Errorf("acquire sandbox retirement fence: %w", err)
		}
		if acquired == 1 {
			return s.startFenceLease(ctx, token, retirementKey, operationKey)
		}
		if !time.Now().Before(nextRenewal) {
			if err := s.renewFenceKeys(ctx, token, distributedFenceTTL, retirementKey); err != nil {
				releaseIntent()
				return nil, nil, err
			}
			nextRenewal = time.Now().Add(distributedFenceTTL / 3)
		}
		if err := waitForFenceRetry(ctx); err != nil {
			releaseIntent()
			return nil, nil, err
		}
	}
}

func waitForFenceRetry(ctx context.Context) error {
	timer := time.NewTimer(distributedFencePollInterval)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func (s *SessionStore) startFenceLease(
	ctx context.Context,
	token string,
	keys ...string,
) (context.Context, func(), error) {
	if len(keys) == 0 {
		return nil, nil, fmt.Errorf("sandbox distributed fence requires at least one key")
	}
	fencedCtx, cancel := context.WithCancelCause(ctx)
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() {
		defer close(done)
		ticker := time.NewTicker(distributedFenceTTL / 3)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-fencedCtx.Done():
				return
			case <-ticker.C:
				if err := s.renewFenceKeys(fencedCtx, token, distributedFenceTTL, keys...); err != nil {
					cancel(err)
					return
				}
			}
		}
	}()
	var once sync.Once
	release := func() {
		once.Do(func() {
			close(stop)
			<-done
			s.releaseFenceKeys(context.Background(), token, keys...)
		})
	}
	return fencedCtx, release, nil
}

func (s *SessionStore) renewFenceKeys(ctx context.Context, token string, ttl time.Duration, keys ...string) error {
	const script = `for i = 1, #KEYS do if redis.call("GET", KEYS[i]) ~= ARGV[1] then return 0 end end; for i = 1, #KEYS do redis.call("PEXPIRE", KEYS[i], ARGV[2]) end; return 1`
	renewed, err := s.client.Eval(ctx, script, keys, token, ttl.Milliseconds()).Int64()
	if err != nil {
		return fmt.Errorf("renew sandbox distributed fence: %w", err)
	}
	if renewed == 0 {
		return fmt.Errorf("sandbox distributed fence ownership was lost")
	}
	return nil
}

func (s *SessionStore) releaseFenceKeys(ctx context.Context, token string, keys ...string) {
	const script = `for i = 1, #KEYS do if redis.call("GET", KEYS[i]) == ARGV[1] then redis.call("DEL", KEYS[i]) end end; return 1`
	_ = s.client.Eval(ctx, script, keys, token).Err()
}

func (s *SessionStore) withTaskLock(
	ctx context.Context,
	provider, workspaceID, taskID, purpose string,
	fn func(context.Context, taskLock) error,
) error {
	key := s.lockKey(provider, workspaceID, taskID, purpose)
	token := uuid.NewString()
	const lockTTL = 30 * time.Second
	for {
		acquired, err := s.client.SetNX(ctx, key, token, lockTTL).Result()
		if err != nil {
			return fmt.Errorf("acquire sandbox creation lock: %w", err)
		}
		if acquired {
			defer s.releaseLock(context.Background(), key, token)
			lockCtx, cancel := context.WithCancel(ctx)
			defer cancel()
			heartbeatDone := make(chan error, 1)
			go s.renewLock(lockCtx, cancel, key, token, lockTTL, heartbeatDone)
			fnErr := fn(lockCtx, taskLock{key: key, token: token})
			cancel()
			heartbeatErr := <-heartbeatDone
			if heartbeatErr != nil {
				return heartbeatErr
			}
			return fnErr
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(50 * time.Millisecond):
		}
	}
}

func (s *SessionStore) renewLock(
	ctx context.Context,
	cancel context.CancelFunc,
	key, token string,
	ttl time.Duration,
	done chan<- error,
) {
	ticker := time.NewTicker(ttl / 3)
	defer ticker.Stop()
	const script = `if redis.call("GET", KEYS[1]) == ARGV[1] then return redis.call("PEXPIRE", KEYS[1], ARGV[2]) else return 0 end`
	for {
		select {
		case <-ctx.Done():
			done <- nil
			return
		case <-ticker.C:
			renewed, err := s.client.Eval(ctx, script, []string{key}, token, ttl.Milliseconds()).Int64()
			if err != nil {
				if ctx.Err() != nil {
					done <- nil
					return
				}
				cancel()
				done <- fmt.Errorf("renew sandbox task lock: %w", err)
				return
			}
			if renewed == 0 {
				cancel()
				done <- fmt.Errorf("sandbox task lock ownership was lost")
				return
			}
		}
	}
}

func (s *SessionStore) getHydration(ctx context.Context, session *Session) (*hydrationRecord, error) {
	data, err := s.client.Get(ctx, s.hydrationKey(session.Provider, session.WorkspaceID, session.TaskID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get sandbox hydration state: %w", err)
	}
	var record hydrationRecord
	if err := json.Unmarshal(data, &record); err != nil {
		return nil, fmt.Errorf("decode sandbox hydration state: %w", err)
	}
	return &record, nil
}

func (s *SessionStore) putHydrationIfSession(
	ctx context.Context,
	session *Session,
	record hydrationRecord,
	lock taskLock,
) error {
	recordData, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("encode sandbox hydration state: %w", err)
	}
	const script = `if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end; local raw = redis.call("GET", KEYS[2]); if not raw then return 0 end; local current = cjson.decode(raw); if current.id == ARGV[2] and current.workspace_id == ARGV[3] and current.task_id == ARGV[4] then redis.call("SET", KEYS[3], ARGV[5], "PX", ARGV[6]); return 1 else return 0 end`
	committed, err := s.client.Eval(
		ctx,
		script,
		[]string{lock.key, s.sessionKey(session.Provider, session.WorkspaceID, session.TaskID), s.hydrationKey(session.Provider, session.WorkspaceID, session.TaskID)},
		lock.token,
		session.ID,
		session.WorkspaceID,
		session.TaskID,
		recordData,
		s.ttl.Milliseconds(),
	).Int64()
	if err != nil {
		return fmt.Errorf("commit sandbox hydration state: %w", err)
	}
	if committed == 0 {
		return fmt.Errorf("sandbox session changed during hydration")
	}
	return nil
}

func (s *SessionStore) releaseLock(ctx context.Context, key, token string) {
	const script = `if redis.call("GET", KEYS[1]) == ARGV[1] then return redis.call("DEL", KEYS[1]) else return 0 end`
	_ = s.client.Eval(ctx, script, []string{key}, token).Err()
}

func (s *SessionStore) sessionKey(provider, workspaceID, taskID string) string {
	return s.prefix + ":provider-session:" + provider + ":" + workspaceID + ":" + taskID
}

func (s *SessionStore) hydrationKey(provider, workspaceID, taskID string) string {
	return s.prefix + ":provider-hydration:" + provider + ":" + workspaceID + ":" + taskID
}

func (s *SessionStore) quarantineKey(provider, workspaceID, taskID string) string {
	return s.prefix + ":provider-quarantine:" + provider + ":" + workspaceID + ":" + taskID
}

func (s *SessionStore) provisioningKey(provider, workspaceID, taskID string) string {
	return s.prefix + ":provider-provisioning:" + provider + ":" + workspaceID + ":" + taskID
}

func (s *SessionStore) lockKey(provider, workspaceID, taskID, purpose string) string {
	return s.prefix + ":provider-session-lock:" + purpose + ":" + provider + ":" + workspaceID + ":" + taskID
}
