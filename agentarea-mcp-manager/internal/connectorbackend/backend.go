// Package connectorbackend adapts a pinned outbound connector to the control
// plane ports.  It deliberately accepts a logical data-plane ID, never an
// address or credential: selection and authentication happen before this
// adapter is constructed.
package connectorbackend

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
)

var ErrOperationFailed = errors.New("connector operation failed")

// OperationHub is the small connectorhub surface used for lifecycle calls.
// Keeping it as a port lets adapter tests model an unavailable transport
// without depending on a streaming RPC implementation.
type OperationHub interface {
	StartOperation(context.Context, string, connectorhub.OperationRequest) (*connectorhub.OperationResult, error)
}

// CapabilityProbe is optional because connectorhub intentionally does not
// publish session internals. A composition root that has a session registry can
// supply one to make Initialize a positive readiness check.
type CapabilityProbe interface {
	ProbeConnector(context.Context, string, connectorhub.Capability) error
}

// Backend is a backends.Backend routed to one already-selected data plane.
type Backend struct {
	hub         OperationHub
	dataPlaneID string
	probe       CapabilityProbe
}

var _ backends.Backend = (*Backend)(nil)

// NewBackend constructs a connector-backed lifecycle backend. dataPlaneID is
// deliberately exact (rather than a selector) so this adapter can never fall
// back to another connector.
func NewBackend(hub OperationHub, dataPlaneID string, probes ...CapabilityProbe) (*Backend, error) {
	if hub == nil {
		return nil, fmt.Errorf("connector hub is required")
	}
	if strings.TrimSpace(dataPlaneID) == "" {
		return nil, fmt.Errorf("data_plane_id is required")
	}
	if len(probes) > 1 {
		return nil, fmt.Errorf("at most one connector capability probe is allowed")
	}
	b := &Backend{hub: hub, dataPlaneID: dataPlaneID}
	if len(probes) == 1 {
		b.probe = probes[0]
	}
	return b, nil
}

func (b *Backend) CreateInstance(ctx context.Context, spec *backends.InstanceSpec) (*backends.InstanceResult, error) {
	if spec == nil {
		return nil, fmt.Errorf("instance spec is required")
	}
	var result backends.InstanceResult
	if err := b.callJSON(ctx, operationKind(connectorproto.OperationKind_OPERATION_KIND_MCP_CREATE), spec, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

func (b *Backend) DeleteInstance(ctx context.Context, instanceID string) error {
	if strings.TrimSpace(instanceID) == "" {
		return fmt.Errorf("instance ID is required")
	}
	err := b.callJSON(ctx, operationKind(connectorproto.OperationKind_OPERATION_KIND_MCP_DELETE), struct {
		InstanceID string `json:"instance_id"`
	}{instanceID}, nil)
	// Retirement is idempotent; a reaped workload is already in the requested
	// state. Other connector failures remain visible to the caller.
	if errors.Is(err, backends.ErrInstanceNotFound) {
		return nil
	}
	return err
}

func (b *Backend) GetInstanceStatus(ctx context.Context, instanceID string) (*backends.InstanceStatus, error) {
	if strings.TrimSpace(instanceID) == "" {
		return nil, fmt.Errorf("instance ID is required")
	}
	var status backends.InstanceStatus
	if err := b.callJSON(ctx, operationKind(connectorproto.OperationKind_OPERATION_KIND_MCP_GET), struct {
		InstanceID string `json:"instance_id"`
	}{instanceID}, &status); err != nil {
		return nil, err
	}
	return &status, nil
}

func (b *Backend) ListInstances(ctx context.Context) ([]*backends.InstanceStatus, error) {
	var payload json.RawMessage
	if err := b.callJSON(ctx, operationKind(connectorproto.OperationKind_OPERATION_KIND_MCP_LIST), struct{}{}, &payload); err != nil {
		return nil, err
	}
	var instances []*backends.InstanceStatus
	if err := json.Unmarshal(payload, &instances); err == nil {
		return instances, nil
	}
	var envelope struct {
		Instances []*backends.InstanceStatus `json:"instances"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("decode connector instance list: %w", err)
	}
	return envelope.Instances, nil
}

func (b *Backend) UpdateInstance(_ context.Context, instanceID string, _ *backends.InstanceSpec) error {
	return fmt.Errorf("connector backend does not support in-place update of %s; delete and recreate the instance", instanceID)
}

func (b *Backend) PerformHealthCheck(ctx context.Context, instanceID string) (*backends.HealthCheckResult, error) {
	if strings.TrimSpace(instanceID) == "" {
		return nil, fmt.Errorf("instance ID is required")
	}
	var health backends.HealthCheckResult
	if err := b.callJSON(ctx, operationKind(connectorproto.OperationKind_OPERATION_KIND_MCP_HEALTH), struct {
		InstanceID string `json:"instance_id"`
	}{instanceID}, &health); err != nil {
		return nil, err
	}
	return &health, nil
}

// Initialize uses an optional session/capability observer. Without one this is
// intentionally a bounded no-op: normal operations still use connectorhub's
// atomic active-session/capability admission, rather than guessing from a URL.
func (b *Backend) Initialize(ctx context.Context) error {
	probeCtx, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	if b.probe == nil {
		select {
		case <-probeCtx.Done():
			return probeCtx.Err()
		default:
			return nil
		}
	}
	if err := b.probe.ProbeConnector(probeCtx, b.dataPlaneID, connectorhub.CapabilityOperations); err != nil {
		return fmt.Errorf("connector data plane %q is not ready: %w", b.dataPlaneID, err)
	}
	return nil
}

func (b *Backend) Shutdown(context.Context) error { return nil }

func (b *Backend) callJSON(ctx context.Context, kind string, input, output any) error {
	payload, err := json.Marshal(input)
	if err != nil {
		return fmt.Errorf("encode connector operation payload: %w", err)
	}
	result, err := b.hub.StartOperation(ctx, b.dataPlaneID, connectorhub.OperationRequest{
		Kind: kind, Payload: payload, ContentType: "application/json",
	})
	if err != nil {
		return err
	}
	if result == nil {
		return fmt.Errorf("%w: connector returned no result", ErrOperationFailed)
	}
	if result.Status != connectorhub.ResultSucceeded {
		return connectorResultError(result)
	}
	if output == nil {
		return nil
	}
	if err := json.Unmarshal(result.Payload, output); err != nil {
		return fmt.Errorf("decode connector %s response: %w", kind, err)
	}
	return nil
}

func connectorResultError(result *connectorhub.OperationResult) error {
	message := strings.TrimSpace(result.Error)
	if message == "" {
		message = string(result.Status)
	}
	if isNotFound(message, result.Payload) {
		return fmt.Errorf("%w: %s", backends.ErrInstanceNotFound, message)
	}
	return fmt.Errorf("%w: %s", ErrOperationFailed, message)
}

func isNotFound(message string, payload []byte) bool {
	var body struct {
		Code   string `json:"code"`
		Status int    `json:"status"`
	}
	if len(payload) > 0 && json.Unmarshal(payload, &body) == nil && (body.Status == 404 || strings.EqualFold(body.Code, "not_found")) {
		return true
	}
	message = strings.ToLower(strings.TrimSpace(message))
	return message == "not_found" || message == "instance not found" || strings.HasPrefix(message, "not found:")
}

func operationKind(kind connectorproto.OperationKind) string { return kind.String() }
