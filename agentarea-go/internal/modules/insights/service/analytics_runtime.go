package service

import (
	"context"
	"crypto/subtle"
	"errors"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/analytics"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/domain"
)

// PulseLockKey is the pulse's pg_try_advisory_xact_lock key: one replica sends it.
const PulseLockKey int64 = 4_107_726_903_118

// Pulse cadence (analytics/pulse.py): every replica ticks hourly; the pulse is due a day after the last.
const (
	PulseTick  = time.Hour
	PulseEvery = 24 * time.Hour
)

// Notice is what the operator is told at startup while analytics is on.
const Notice = "Anonymous usage analytics is on (what is sent: https://docs.agentarea.ai/self-host/analytics). " +
	"Turn it off with AGENTAREA_ANALYTICS_ENABLED=false."

// ErrSignupHookOff is the sign-up hook without AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY (404).
var ErrSignupHookOff = errors.New("sign-up hook is off")

// ErrSignupHookKey is a sign-up hook call without the key (401).
var ErrSignupHookKey = errors.New("sign-up hook key mismatch")

// PulseLock takes the pulse lock and the installation row (store.Installation.LockForPulse).
type PulseLock interface {
	LockForPulse(ctx context.Context, d db.Database, key db.LockKey, now time.Time, fn func(ctx context.Context, row domain.Installation) (bool, error)) (bool, error)
}

// Signups stores sign-up attributions (store.Signups).
type Signups interface {
	Insert(ctx context.Context, g db.Global, identityID string, createdAt time.Time, method *string, a domain.Attribution, now time.Time) (bool, error)
}

// AnalyticsDeps are the analytics runtime's ports.
type AnalyticsDeps struct {
	DB            db.Database
	Installations Installations
	Lock          PulseLock
	Signups       Signups
	Collector     Collector
	// Counter is the process's counter handle the started sender is attached to.
	Counter *analytics.Handle
	// Pulse returns the owners' pulse reads; called once the pulse runs.
	Pulse            func() PulseReads
	Enabled          bool
	Version, Edition string
	SignupHookKey    string
	OwnDomains       []string
	Now              func() time.Time
	Log              *slog.Logger
}

// Analytics is start_analytics, the InstallationPulse and the sign-up hook over one sender.
type Analytics struct {
	d      AnalyticsDeps
	sender atomic.Pointer[Sender]
	stop   context.CancelFunc
	wg     sync.WaitGroup
}

// NewAnalytics builds the runtime; nothing starts until Start.
func NewAnalytics(d AnalyticsDeps) *Analytics {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Analytics{d: d}
}

// Start is start_analytics: off, nothing; on, the sender reports as this installation, sends
// every FlushEvery and takes the process's counts. It never fails the process: if it cannot
// start, analytics stays off for it.
func (a *Analytics) Start(ctx context.Context) error {
	if !a.d.Enabled {
		return nil
	}
	id, err := a.d.Installations.GetOrCreate(ctx, a.d.DB.Global(), a.d.Now())
	if err != nil {
		a.d.Log.ErrorContext(ctx, "Usage analytics could not start; it is off for this process", "error", err)
		return nil
	}
	a.d.Log.InfoContext(ctx, Notice)
	s := NewSender(id, a.d.Version, a.d.Edition, a.d.Collector, a.d.Now, a.d.Log)
	a.sender.Store(s)
	if a.d.Counter != nil {
		a.d.Counter.Attach(s)
	}
	run, cancel := context.WithCancel(context.WithoutCancel(ctx))
	a.stop = cancel
	a.wg.Go(func() { s.Run(run, FlushEvery) })
	return nil
}

// Stop stops counting and sends what is left.
func (a *Analytics) Stop(ctx context.Context) error {
	s := a.sender.Swap(nil)
	if s == nil {
		return nil
	}
	if a.d.Counter != nil {
		a.d.Counter.Detach()
	}
	a.stop()
	a.wg.Wait()
	s.SendAll(ctx)
	return nil
}

// RunPulse is InstallationPulse's loop: a try every tick until ctx ends; a failed try is logged
// and retried next tick. Without a started sender it waits for ctx.
func (a *Analytics) RunPulse(ctx context.Context, tick time.Duration) error {
	for {
		if a.sender.Load() != nil {
			if _, err := a.PulseOnce(ctx); err != nil && ctx.Err() == nil {
				a.d.Log.WarnContext(ctx, "Installation pulse failed; retried next tick", "error", err)
			}
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(tick):
		}
	}
}

// PulseOnce sends the pulse if it is due and this replica holds the lock; whether it was sent.
func (a *Analytics) PulseOnce(ctx context.Context) (bool, error) {
	s := a.sender.Load()
	if s == nil {
		return false, nil
	}
	now := a.d.Now()
	var props map[string]any
	sent, err := a.d.Lock.LockForPulse(ctx, a.d.DB, db.Key(PulseLockKey), now, func(ctx context.Context, row domain.Installation) (bool, error) {
		if row.LastPulse != nil && now.UTC().Sub(*row.LastPulse) < PulseEvery {
			return false, nil
		}
		collected, err := CollectPulse(ctx, a.d.Pulse(), now)
		if err != nil {
			return false, err
		}
		props = map[string]any{"install_age_days": int(now.UTC().Sub(row.CreatedAt).Hours() / 24)}
		for k, v := range collected {
			props[k] = v
		}
		return true, nil
	})
	if err != nil || !sent {
		return false, err
	}
	s.Enqueue(map[string]any{"event": "installation_pulse", "properties": props})
	s.Flush(ctx)
	return true, nil
}

// SignupHook is the body Kratos's after-registration hook posts.
type SignupHook struct {
	IdentityID string
	CreatedAt  time.Time
	RequestURL *string
}

// CheckSignupKey is _hook_key: no key configured is ErrSignupHookOff, another authorization
// ErrSignupHookKey.
func (a *Analytics) CheckSignupKey(authorization string) error {
	if a.d.SignupHookKey == "" {
		return ErrSignupHookOff
	}
	if subtle.ConstantTimeCompare([]byte(authorization), []byte(a.d.SignupHookKey)) != 1 {
		return ErrSignupHookKey
	}
	return nil
}

// RecordSignup is record_signup: the sign-up's channel stored once per identity; the first store
// also queues sign_up while the sender runs.
func (a *Analytics) RecordSignup(ctx context.Context, hook SignupHook, method string) error {
	m := domain.SignupMethod(method)
	attr := domain.AttributionFromRequestURL(hook.RequestURL, a.d.OwnDomains)
	inserted, err := a.d.Signups.Insert(ctx, a.d.DB.Global(), hook.IdentityID, hook.CreatedAt, m, attr, a.d.Now())
	if err != nil {
		return err
	}
	s := a.sender.Load()
	if !inserted || s == nil || !a.d.Enabled {
		return nil
	}
	id, err := a.d.Installations.GetOrCreate(ctx, a.d.DB.Global(), a.d.Now())
	if err != nil {
		return err
	}
	s.Enqueue(map[string]any{
		"event":   "sign_up",
		"user_id": domain.Pseudonymize(id, hook.IdentityID),
		"properties": map[string]any{
			"channel": attr.Channel, "method": m, "landing_host": attr.LandingHost, "landing_path": attr.LandingPath,
			"referrer_host": attr.ReferrerHost, "utm_source": attr.UTMSource, "utm_medium": attr.UTMMedium,
			"utm_campaign": attr.UTMCampaign,
		},
	})
	return nil
}
