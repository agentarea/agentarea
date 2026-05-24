package sandboxcontrol

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

const (
	ExecutionStatusQueued    = "queued"
	ExecutionStatusClaimed   = "claimed"
	ExecutionStatusRunning   = "running"
	ExecutionStatusCompleted = "completed"
	ExecutionStatusFailed    = "failed"
	ExecutionStatusCancelled = "cancelled"
)

const (
	EventTypeExecutionRequested = "com.agentarea.sandbox.execution.requested"
	EventTypeExecutionClaimed   = "com.agentarea.sandbox.execution.claimed"
	EventTypeExecutionStarted   = "com.agentarea.sandbox.execution.started"
	EventTypeExecutionProgress  = "com.agentarea.sandbox.execution.progress"
	EventTypeExecutionCompleted = "com.agentarea.sandbox.execution.completed"
	EventTypeExecutionFailed    = "com.agentarea.sandbox.execution.failed"
	EventTypeExecutionCancelled = "com.agentarea.sandbox.execution.cancelled"
)

const (
	DefaultExecutionRequestStream = "agentarea.sandbox.execution.requests"
	DefaultExecutionEventStream   = "agentarea.sandbox.execution.events"
)

// ExecutionCreateRequest is the control-plane request to schedule sandbox work.
// It is intentionally runtime-neutral: no pod names, runner URLs, or provider
// paths leak into the workflow/API contract.
type ExecutionCreateRequest struct {
	SessionID   string                   `json:"session_id,omitempty"`
	WorkflowID  string                   `json:"workflow_id,omitempty"`
	TaskID      string                   `json:"task_id,omitempty"`
	WorkspaceID string                   `json:"workspace_id,omitempty"`
	Runtime     RuntimeSelector          `json:"runtime,omitempty"`
	Command     warmpool.ExecuteRequest  `json:"command"`
	Metadata    map[string]string        `json:"metadata,omitempty"`
	InputRefs   []SandboxObjectReference `json:"input_refs,omitempty"`
}

type RuntimeSelector struct {
	Provider string            `json:"provider,omitempty"`
	Region   string            `json:"region,omitempty"`
	Labels   map[string]string `json:"labels,omitempty"`
}

type SandboxObjectReference struct {
	URI         string `json:"uri"`
	ContentType string `json:"content_type,omitempty"`
	Size        int64  `json:"size,omitempty"`
	SHA256      string `json:"sha256,omitempty"`
}

type ExecutionRecord struct {
	ID          string                    `json:"id"`
	SessionID   string                    `json:"session_id,omitempty"`
	WorkflowID  string                    `json:"workflow_id,omitempty"`
	TaskID      string                    `json:"task_id,omitempty"`
	WorkspaceID string                    `json:"workspace_id,omitempty"`
	Runtime     RuntimeSelector           `json:"runtime,omitempty"`
	Status      string                    `json:"status"`
	Command     warmpool.ExecuteRequest   `json:"command,omitempty"`
	Metadata    map[string]string         `json:"metadata,omitempty"`
	InputRefs   []SandboxObjectReference  `json:"input_refs,omitempty"`
	OutputRefs  []SandboxObjectReference  `json:"output_refs,omitempty"`
	Result      *warmpool.ExecuteResponse `json:"result,omitempty"`
	Error       string                    `json:"error,omitempty"`
	CreatedAt   time.Time                 `json:"created_at"`
	UpdatedAt   time.Time                 `json:"updated_at"`
	StartedAt   *time.Time                `json:"started_at,omitempty"`
	CompletedAt *time.Time                `json:"completed_at,omitempty"`
}

type ExecutionEventRequest struct {
	EventType  string                    `json:"event_type"`
	Status     string                    `json:"status,omitempty"`
	Error      string                    `json:"error,omitempty"`
	OutputRefs []SandboxObjectReference  `json:"output_refs,omitempty"`
	Result     *warmpool.ExecuteResponse `json:"result,omitempty"`
	Metadata   map[string]string         `json:"metadata,omitempty"`
}

type CloudEvent struct {
	SpecVersion     string         `json:"specversion"`
	Type            string         `json:"type"`
	Source          string         `json:"source"`
	ID              string         `json:"id"`
	Time            time.Time      `json:"time"`
	DataContentType string         `json:"datacontenttype,omitempty"`
	CorrelationID   string         `json:"correlationid,omitempty"`
	Data            map[string]any `json:"data"`
}

func newID(prefix string) string {
	var b [12]byte
	if _, err := rand.Read(b[:]); err != nil {
		return prefix + "_" + time.Now().UTC().Format("20060102150405.000000000")
	}
	return prefix + "_" + hex.EncodeToString(b[:])
}

// ExecutionFromCloudEvent decodes the execution record embedded in a sandbox
// CloudEvent. Runners use this only to discover the execution id; the durable
// Redis record remains the source of truth before execution starts.
func ExecutionFromCloudEvent(payload []byte) (*ExecutionRecord, error) {
	var envelope struct {
		Data struct {
			Execution json.RawMessage `json:"execution"`
		} `json:"data"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("decode sandbox cloud event: %w", err)
	}
	if len(envelope.Data.Execution) == 0 {
		return nil, fmt.Errorf("sandbox cloud event has no execution payload")
	}
	var record ExecutionRecord
	if err := json.Unmarshal(envelope.Data.Execution, &record); err != nil {
		return nil, fmt.Errorf("decode sandbox execution payload: %w", err)
	}
	if record.ID == "" {
		return nil, fmt.Errorf("sandbox execution payload has no id")
	}
	return &record, nil
}
