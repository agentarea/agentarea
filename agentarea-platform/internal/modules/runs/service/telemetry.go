package service

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// RunTelemetry records run transitions (ADR-0048 agentarea.run.transitions
// and agentarea.run.duration); failureReason is one of domain.RunFailure*,
// elapsed is set only on a terminal status of a run that has started.
type RunTelemetry interface {
	RunTransition(status, failureReason string, elapsed *time.Duration)
}

// recordRunTransition counts a status update that moved the task (record_run_transition).
func (s *Service) recordRunTransition(u domain.StatusUpdate) {
	if s.d.Telemetry == nil {
		return
	}
	var elapsed *time.Duration
	if u.RunStartedAt != nil && domain.TerminalRunStatus(u.Status) {
		d := max(s.now().Sub(*u.RunStartedAt), 0)
		elapsed = &d
	}
	s.d.Telemetry.RunTransition(u.Status, domain.RunFailureReason(u.Status, u.FailureReason), elapsed)
}
