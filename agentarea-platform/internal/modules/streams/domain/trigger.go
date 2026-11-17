package domain

import (
	"errors"
	"fmt"
	"regexp"
	"time"
)

// Trigger types (TriggerType).
const (
	TypeCron   = "cron"
	TypeStream = "stream"
)

// Trigger statuses (trigger_status).
const (
	StatusActive     = "active"
	StatusInactive   = "inactive"
	StatusNeedsOwner = "needs_owner"
)

// BatchMaxEvents is the largest batch window a trigger may ask for (AGENTAREA_TRIGGER_BATCH_MAX_EVENTS default).
const BatchMaxEvents = 100

var (
	// ErrNotFound: no such trigger in the workspace.
	ErrNotFound = errors.New("trigger not found")
	// ErrNoSubscription: the trigger has no stream subscription to change.
	ErrNoSubscription = errors.New("trigger has no stream subscription")
)

// ValidationError is a refused trigger configuration (TriggerValidationError): a 400.
type ValidationError struct{ Msg string }

func (e *ValidationError) Error() string { return e.Msg }

// Invalid is a ValidationError with msg.
func Invalid(msg string) error { return &ValidationError{Msg: msg} }

// Session is what the next event of the same session does.
type Session struct {
	Continue    *bool   `json:"continue,omitempty"`
	IdleTimeout *string `json:"idle_timeout,omitempty"`
}

// Batch is the window a stream trigger fires per.
type Batch struct {
	Window    *string `json:"window,omitempty"`
	MaxEvents *int    `json:"max_events,omitempty"`
}

// Binding is a stream trigger's subscription as its stream sees it.
type Binding struct {
	StreamID    string
	Filter      map[string]any
	LastEventAt *time.Time
}

// Trigger is a stored trigger (TriggerResponse's source).
type Trigger struct {
	ID               string
	WorkspaceID      string
	Name             string
	Description      string
	AgentID          string
	TaskDefinitionID *string
	Type             string
	IsActive         bool
	TaskParameters   map[string]any
	Conditions       map[string]any
	FailureThreshold int
	Consecutive      int
	LastExecutionAt  *time.Time
	CronExpression   *string
	Timezone         *string
	NeedsNewOwnerAt  *time.Time
	Session          *Session
	Batch            *Batch
	CreatedBy        string
	CreatedAt        time.Time
	UpdatedAt        time.Time
	Binding          *Binding
}

// ShouldDisable is should_disable_due_to_failures.
func (t Trigger) ShouldDisable() bool { return t.Consecutive >= t.FailureThreshold }

// Status is trigger_status: "needs_owner" while stopped by its owner's loss of access.
func (t Trigger) Status() string {
	switch {
	case t.IsActive:
		return StatusActive
	case t.NeedsNewOwnerAt != nil:
		return StatusNeedsOwner
	default:
		return StatusInactive
	}
}

// NewTrigger is a TriggerCreate after the route read it.
type NewTrigger struct {
	Name             string
	Description      string
	AgentID          string
	Type             string
	StreamID         *string
	EventFilter      map[string]any
	TaskDefinitionID *string
	TaskParameters   map[string]any
	Conditions       map[string]any
	FailureThreshold int
	CronExpression   *string
	Timezone         *string
	Enabled          bool
	Session          *Session
	Batch            *Batch
}

// Validate applies the rules that need no store (validate_trigger_configuration
// minus conditions, the batch cap and the cron grammar, which the service checks).
func (n NewTrigger) Validate() error {
	if n.Name == "" || isBlank(n.Name) {
		return Invalid("Trigger name is required")
	}
	if err := CheckConditions(n.Conditions); err != nil {
		return err
	}
	switch n.Type {
	case TypeCron:
		if n.CronExpression == nil || isBlank(*n.CronExpression) {
			return Invalid("Cron expression is required for CRON triggers")
		}
		if n.Timezone == nil || isBlank(*n.Timezone) {
			return Invalid("Timezone is required for CRON triggers")
		}
		if n.TaskDefinitionID == nil && !hasTaskText(n.TaskParameters) {
			return Invalid("Task text is required for CRON triggers")
		}
	case TypeStream:
		if n.StreamID == nil {
			return Invalid("stream_id is required for STREAM triggers")
		}
		return ValidateEventFilter(n.EventFilter)
	default:
		return Invalid("trigger_type must be cron or stream")
	}
	return nil
}

func hasTaskText(p map[string]any) bool {
	s, ok := p["text"].(string)
	return ok && !isBlank(s)
}

func isBlank(s string) bool {
	for _, r := range s {
		if r != ' ' && r != '\t' && r != '\n' && r != '\r' {
			return false
		}
	}
	return true
}

// ReservedTaskParameters are written only by the trigger that received an event (reserved_task_parameters.py).
// DropReserved removes the reserved keys of an edit's parameters.

// Execution is a trigger_executions row (TriggerExecutionResponse's source).
type Execution struct {
	ID              string
	TriggerID       string
	ExecutedAt      time.Time
	Status          string
	TaskID          *string
	ExecutionTimeMs int
	ErrorMessage    *string
	TriggerData     map[string]any
	WorkflowID      *string
	RunID           *string
	FiredBy         *string
}

// ValidExecutionStatus reports whether s names an ExecutionStatus.
func ValidExecutionStatus(s string) bool {
	switch s {
	case "success", "failed", "timeout", "cancelled", "skipped", "batched":
		return true
	}
	return false
}

var (
	idleTimeoutPattern = regexp.MustCompile(`^[0-9]+[smhd]$`)
	windowPattern      = regexp.MustCompile(`^[1-9][0-9]*[smhd]$`)
)

// ValidateSession is TriggerSession's field rules.
func ValidateSession(s *Session) error {
	if s != nil && s.IdleTimeout != nil && !idleTimeoutPattern.MatchString(*s.IdleTimeout) {
		return Invalid("session.idle_timeout: String should match pattern '^[0-9]+[smhd]$'")
	}
	return nil
}

// ValidateBatch is TriggerBatchWindow's field rules plus _validate_batch: the
// deployment's cap, and task text unless a saved task is asked.
func ValidateBatch(b *Batch, maxEvents int, params map[string]any, taskDefinitionID *string) error {
	if b == nil {
		return nil
	}
	if b.Window != nil && !windowPattern.MatchString(*b.Window) {
		return Invalid("batch.window: String should match pattern '^[1-9][0-9]*[smhd]$'")
	}
	if b.MaxEvents != nil && *b.MaxEvents < 2 {
		return Invalid("batch.max_events: Input should be greater than or equal to 2")
	}
	if b.Window == nil && b.MaxEvents == nil {
		return Invalid("batch: a batch needs a window or max_events")
	}
	if b.MaxEvents != nil && *b.MaxEvents > maxEvents {
		return Invalid(fmt.Sprintf("batch max_events is %d; a batch holds at most %d events", *b.MaxEvents, maxEvents))
	}
	if taskDefinitionID != nil {
		return nil
	}
	if !hasTaskText(params) {
		return Invalid("a batched trigger needs task text: what to do with the events of each batch")
	}
	return nil
}
