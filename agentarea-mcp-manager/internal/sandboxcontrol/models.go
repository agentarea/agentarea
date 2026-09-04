package sandboxcontrol

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
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
	SessionID            string                  `json:"session_id,omitempty"`
	WorkflowID           string                  `json:"workflow_id,omitempty"`
	TaskID               string                  `json:"task_id,omitempty"`
	WorkspaceID          string                  `json:"workspace_id,omitempty"`
	Runtime              RuntimeSelector         `json:"runtime,omitempty"`
	Command              warmpool.ExecuteRequest `json:"command"`
	WorkspaceManifestRef *workspace.ManifestRef  `json:"workspace_manifest_ref,omitempty"`
}

// RuntimeSelector expresses where/how a task may run. Only Region is honored by
// placement today (see internal/sandboxplacement). A provider/isolation-tier
// selector is intentionally NOT present until it is actually wired for routing,
// so the contract never advertises a selector that silently does nothing.
type RuntimeSelector struct {
	Region string `json:"region,omitempty"`
}

type SandboxObjectReference = workspace.Entry

type ExecutionRecord struct {
	ID                   string                    `json:"id"`
	Revision             int64                     `json:"revision"`
	SessionID            string                    `json:"session_id,omitempty"`
	WorkflowID           string                    `json:"workflow_id,omitempty"`
	TaskID               string                    `json:"task_id,omitempty"`
	WorkspaceID          string                    `json:"workspace_id,omitempty"`
	Runtime              RuntimeSelector           `json:"runtime,omitempty"`
	Status               string                    `json:"status"`
	Command              warmpool.ExecuteRequest   `json:"command,omitempty"`
	Metadata             map[string]string         `json:"metadata,omitempty"`
	WorkspaceManifestRef *workspace.ManifestRef    `json:"workspace_manifest_ref,omitempty"`
	OutputRefs           []SandboxObjectReference  `json:"output_refs,omitempty"`
	Result               *warmpool.ExecuteResponse `json:"result,omitempty"`
	Error                string                    `json:"error,omitempty"`
	CreatedAt            time.Time                 `json:"created_at"`
	UpdatedAt            time.Time                 `json:"updated_at"`
	QueueExpiresAt       time.Time                 `json:"queue_expires_at"`
	StartedAt            *time.Time                `json:"started_at,omitempty"`
	ExecutionExpiresAt   *time.Time                `json:"execution_expires_at,omitempty"`
	CompletedAt          *time.Time                `json:"completed_at,omitempty"`
}

func (r *ExecutionCreateRequest) UnmarshalJSON(data []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, field := range []string{"args", "env", "script", "metadata", "input_files", "content_base64", "script_content", "script_name"} {
		if _, exists := fields[field]; exists {
			return fmt.Errorf("unsupported_contract_version: top-level inline execution fields are forbidden; use command.command_body and manager-owned task inputs")
		}
	}
	type requestAlias ExecutionCreateRequest
	var decoded requestAlias
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	*r = ExecutionCreateRequest(decoded)
	return nil
}

func (r *RuntimeSelector) UnmarshalJSON(data []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	if _, exists := fields["labels"]; exists {
		return fmt.Errorf("unsupported_contract_version: runtime labels are forbidden")
	}
	type selectorAlias RuntimeSelector
	var decoded selectorAlias
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	*r = RuntimeSelector(decoded)
	return nil
}

type ExecutionEventRequest struct {
	EventType            string                    `json:"event_type"`
	Status               string                    `json:"status,omitempty"`
	Error                string                    `json:"error,omitempty"`
	OutputRefs           []SandboxObjectReference  `json:"output_refs,omitempty"`
	Result               *warmpool.ExecuteResponse `json:"result,omitempty"`
	Metadata             map[string]string         `json:"metadata,omitempty"`
	WorkspaceManifestRef *workspace.ManifestRef    `json:"workspace_manifest_ref,omitempty"`
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

// ExecutionFromCloudEvent decodes only the execution identity embedded in a
// sandbox CloudEvent. Durable records are fetched separately by ID.
func ExecutionFromCloudEvent(payload []byte) (*ExecutionRecord, error) {
	var envelope struct {
		Data struct {
			ExecutionID string `json:"execution_id"`
		} `json:"data"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("decode sandbox cloud event: %w", err)
	}
	if envelope.Data.ExecutionID == "" {
		return nil, fmt.Errorf("sandbox execution payload has no id")
	}
	return &ExecutionRecord{ID: envelope.Data.ExecutionID}, nil
}
