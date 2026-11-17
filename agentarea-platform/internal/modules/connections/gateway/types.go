// Package gateway is the MCP data path: ANY /mcp/{instance_id}/mcp proxied to
// the instance's workload (started on demand, one request lease per call) or
// to its remote URL, DELETE /mcp/{instance_id} to retire the workload, and the
// instance storage API. The lifecycle behind it is connections/runtime.
package gateway

import (
	"context"
	"errors"
	"net/http"
	"time"
)

// Headers the gateway owns; a workload's response never carries them.
const (
	StartingHeader     = "X-AgentArea-MCP-Starting"
	StartFailureHeader = "X-AgentArea-MCP-Start-Failure"
	AuthHeader         = "X-AgentArea-Manager-Authorization"
)

// ErrStartInProgress is another caller holding the instance's lifecycle.
var ErrStartInProgress = errors.New("MCP instance start is already in progress")

// ErrInstanceBusy is a retirement refused while a request holds the workload.
var ErrInstanceBusy = errors.New("MCP instance has active requests")

// ErrInstanceNotFound is an instance id with no row.
var ErrInstanceNotFound = errors.New("MCP instance not found")

// StartFailure is a classified startup failure: the reason is safe to show the
// caller and the retry delay is the backoff in force.
type StartFailure interface {
	error
	FailureReason() string
	RetryDelay() time.Duration
}

// Runtime is the lifecycle the gateway serves (connections/runtime).
type Runtime interface {
	// Load resolves the instance; ErrInstanceNotFound when it has no row.
	Load(ctx context.Context, instanceID string) (Target, error)
	// Admit makes the container instance ready and opens a request lease.
	// report records the cold start when one happens.
	Admit(ctx context.Context, t Target, requestID string, report *ColdStart) (Admission, error)
	// URLHeaders resolves a url instance's headers at the moment of use.
	URLHeaders(ctx context.Context, t Target) (map[string]string, error)
	// Retire stops the workload so the next request starts it from the current spec.
	Retire(ctx context.Context, instanceID string) error
}

// Target is a loaded instance: a container-backed one, or a URL one when URL is set.
type Target struct {
	InstanceID  string
	WorkspaceID string
	URL         *URLServer
}

// URLServer is a url-transport instance.
type URLServer struct {
	EndpointURL  string
	AuthConfigID string
	ManagedBy    string
	// Headers are literals or {"secret_name": ...} references; EnvVars name
	// the instance's own secrets sent as headers. URLHeaders resolves both.
	Headers map[string]any
	EnvVars []string
}

// Admission is an admitted request to a running workload.
type Admission struct {
	Upstream string
	// Remote marks the data-plane hop, which may be https and is authorized by Authorize.
	Remote    bool
	Authorize func(*http.Request) bool
	Lease     Lease
}

// Lease is the request lease that keeps the workload from being reaped.
type Lease interface {
	Heartbeat(ctx context.Context) error
	Finish(ctx context.Context) error
}

// Answer is what the gateway itself answered, when it did not proxy.
type Answer string

const (
	AnswerStarting    Answer = "starting"
	AnswerStartFailed Answer = "start_failed"
)

// ColdStartOutcome is how a cold start ended.
type ColdStartOutcome string

const (
	ColdStartReady   ColdStartOutcome = "ready"
	ColdStartFailed  ColdStartOutcome = "failed"
	ColdStartTimeout ColdStartOutcome = "timeout"
)

// Activation steps a cold start fails in.
const (
	StepCreate    = "create"
	StepRunning   = "running"
	StepListening = "listening"
	StepObserver  = "observer"
	StepAdmission = "admission"
)

// ColdStart is one workload activation. The runtime fills it; Settle
// classifies it once the start ended.
type ColdStart struct {
	Outcome   ColdStartOutcome
	Reason    string
	Running   time.Duration
	Listening time.Duration
	Total     time.Duration

	Activated bool
	FailedIn  string
}

// RequestStarted is a request the gateway accepted.
type RequestStarted struct {
	RequestID   string
	InstanceID  string
	WorkspaceID string
	Method      string
	MCPMethod   *string
	MCPName     *string
	StartedAt   time.Time
}

// RequestCompleted is a request the gateway finished.
type RequestCompleted struct {
	RequestStarted
	EndedAt    time.Time
	StatusCode int
	Canceled   bool
	Answer     Answer
	ColdStart  *ColdStart
}

// RequestObserver sees every request; a Started error refuses it with 503.
type RequestObserver interface {
	Started(ctx context.Context, r RequestStarted) error
	Completed(ctx context.Context, r RequestCompleted) error
}
