package polling

import (
	"context"
	"database/sql"
	"log/slog"
	"sync"
	"time"

	"github.com/agentarea/event-service/internal/channels"
	"github.com/agentarea/event-service/internal/claim"
	"github.com/agentarea/event-service/internal/submit"
	"github.com/agentarea/event-service/internal/trigger"
)

// EventSubmitter abstracts how polled events are submitted for processing.
type EventSubmitter interface {
	SubmitEvent(ctx context.Context, triggerID string, event submit.Event, channelOrigin map[string]any) error
}

// Manager owns the set of running polling goroutines and reconciles them
// against the set of active triggers loaded from the database.
type Manager struct {
	db           *sql.DB
	submitter    EventSubmitter
	claimer      *claim.RedisClaimer
	pollInterval time.Duration
	maxPollers   int

	mu      sync.Mutex
	pollers map[string]context.CancelFunc // trigger_id -> cancel
}

// NewManager creates a new polling Manager.
func NewManager(
	db *sql.DB,
	submitter EventSubmitter,
	claimer *claim.RedisClaimer,
	pollInterval time.Duration,
	maxPollers int,
) *Manager {
	return &Manager{
		db:           db,
		submitter:    submitter,
		claimer:      claimer,
		pollInterval: pollInterval,
		maxPollers:   maxPollers,
		pollers:      make(map[string]context.CancelFunc),
	}
}

// Run reconciles running pollers every pollInterval until ctx is cancelled.
func (m *Manager) Run(ctx context.Context) error {
	slog.Info("polling manager started", "interval", m.pollInterval)
	ticker := time.NewTicker(m.pollInterval)
	defer ticker.Stop()

	// Run an initial reconcile immediately
	m.reconcile(ctx)

	for {
		select {
		case <-ctx.Done():
			m.stopAll()
			return ctx.Err()
		case <-ticker.C:
			m.reconcile(ctx)
		}
	}
}

// reconcile loads active triggers and starts/stops pollers as needed.
func (m *Manager) reconcile(ctx context.Context) {
	triggers, err := trigger.LoadActivePollingTriggers(ctx, m.db)
	if err != nil {
		slog.Error("failed to load active polling triggers", "error", err)
		return
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	// Build set of desired trigger IDs
	desired := make(map[string]trigger.Trigger, len(triggers))
	for _, t := range triggers {
		desired[t.ID] = t
	}

	// Stop pollers for triggers that are no longer active
	for id, cancel := range m.pollers {
		if _, ok := desired[id]; !ok {
			slog.Info("stopping poller for removed/disabled trigger", "trigger_id", id)
			cancel()
			delete(m.pollers, id)
		}
	}

	// Start pollers for new triggers (respecting maxPollers)
	for id, t := range desired {
		if _, running := m.pollers[id]; running {
			continue
		}
		if len(m.pollers) >= m.maxPollers {
			slog.Warn("max pollers reached, skipping trigger", "trigger_id", id, "max", m.maxPollers)
			continue
		}
		m.startPoller(ctx, t)
	}
}

// startPoller launches a goroutine for the given trigger.
// Must be called with m.mu held.
func (m *Manager) startPoller(ctx context.Context, t trigger.Trigger) {
	// Resolve channel poller from registry
	factory := channels.Get(t.DataExtractor)
	if factory == nil {
		slog.Error("no channel poller registered for extractor", "trigger_id", t.ID, "extractor", t.DataExtractor)
		return
	}

	poller := factory(t.DataExtractorConfig)
	if poller == nil {
		slog.Error("channel factory returned nil (bad config?)", "trigger_id", t.ID, "extractor", t.DataExtractor)
		return
	}

	pollerCtx, cancel := context.WithCancel(ctx)
	m.pollers[t.ID] = cancel

	go func() {
		defer func() {
			cancel()
			m.mu.Lock()
			delete(m.pollers, t.ID)
			m.mu.Unlock()
			slog.Info("poller stopped", "trigger_id", t.ID)
		}()

		// Try to claim this trigger
		claimed, err := m.claimer.TryClaim(pollerCtx, t.ID)
		if err != nil {
			slog.Error("failed to claim trigger", "trigger_id", t.ID, "error", err)
			return
		}
		if !claimed {
			slog.Debug("trigger already claimed by another worker, skipping", "trigger_id", t.ID)
			return
		}
		defer func() {
			releaseCtx := context.Background()
			if err := m.claimer.Release(releaseCtx, t.ID); err != nil {
				slog.Warn("failed to release claim", "trigger_id", t.ID, "error", err)
			}
		}()

		slog.Info("starting poller", "trigger_id", t.ID, "name", t.Name, "extractor", t.DataExtractor)

		// Heartbeat renewal every 20s
		renewTicker := time.NewTicker(20 * time.Second)
		go func() {
			defer renewTicker.Stop()
			for {
				select {
				case <-pollerCtx.Done():
					return
				case <-renewTicker.C:
					if err := m.claimer.Renew(pollerCtx, t.ID); err != nil {
						slog.Warn("failed to renew claim", "trigger_id", t.ID, "error", err)
					}
				}
			}
		}()

		m.runPoller(pollerCtx, t, poller)
	}()
}

// runPoller runs the generic poll loop for any channel type.
func (m *Manager) runPoller(ctx context.Context, t trigger.Trigger, poller channels.ChannelPoller) {
	// Load last offset from persisted state
	var offset int64
	if t.DataExtractorState != nil {
		if v, ok := t.DataExtractorState["offset"].(float64); ok {
			offset = int64(v)
		}
	}

	RunLoop(ctx, t.ID, func(ctx context.Context) error {
		slog.Info("polling", "trigger_id", t.ID, "offset", offset)
		result, err := poller.Poll(ctx, offset)
		if err != nil {
			return err
		}

		slog.Info("poll result", "trigger_id", t.ID, "events", len(result.Events), "new_offset", result.NewOffset)

		if len(result.Events) == 0 {
			if result.NewOffset > 0 {
				offset = result.NewOffset
			}
			return nil
		}

		slog.Info("received events", "trigger_id", t.ID, "count", len(result.Events))

		// Submit each event individually (don't advance offset on failure)
		for _, event := range result.Events {
			origin := result.ChannelOrigin
			if origin == nil {
				origin = map[string]any{}
			}
			// Add trigger_id for credential lookup on response routing
			origin["trigger_id"] = t.ID

			if err := m.submitter.SubmitEvent(ctx, t.ID, event, origin); err != nil {
				slog.Warn("failed to submit event, not advancing offset",
					"trigger_id", t.ID,
					"error", err,
				)
				return err
			}
		}

		// Advance offset after all events submitted
		if result.NewOffset > 0 {
			offset = result.NewOffset
		}

		// Persist state
		state := map[string]any{"offset": offset}
		if err := trigger.UpdateExtractorState(ctx, m.db, t.ID, state); err != nil {
			slog.Warn("failed to persist extractor state", "trigger_id", t.ID, "error", err)
		}

		return nil
	})
}

// stopAll cancels all running pollers. Called on shutdown.
func (m *Manager) stopAll() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for id, cancel := range m.pollers {
		slog.Info("stopping poller on shutdown", "trigger_id", id)
		cancel()
	}
	m.pollers = make(map[string]context.CancelFunc)
}
