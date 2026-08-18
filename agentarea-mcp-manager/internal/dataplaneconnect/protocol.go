// Package dataplaneconnect implements the outbound control-plane connection used
// by the data-plane agent. It intentionally does not expose an HTTP listener.
package dataplaneconnect

const ProtocolVersion = "v1"

const (
	EnrollmentExchangePath = "/v1/data-planes/enrollment/exchange"
	HeartbeatPathFormat    = "/v1/data-planes/%s/heartbeat"
)

// IDs deliberately have different types: a logical data plane can have several
// connector installations over its lifetime.
type DataPlaneID string
type ConnectorInstanceID string

type Capabilities struct {
	MCP     bool `json:"mcp"`
	Sandbox bool `json:"sandbox"`
}

type EnrollmentRequest struct {
	ProtocolVersion string `json:"protocol_version"`
	// DataPlaneID is optional on enrollment. When supplied, it is checked
	// against the data plane selected by the enrollment token.
	DataPlaneID         DataPlaneID         `json:"data_plane_id,omitempty"`
	ConnectorInstanceID ConnectorInstanceID `json:"connector_instance_id"`
	EnrollmentToken     string              `json:"enrollment_token"`
	Capabilities        Capabilities        `json:"capabilities"`
}

type EnrollmentResponse struct {
	DataPlaneID    DataPlaneID `json:"data_plane_id"`
	NodeCredential string      `json:"node_credential"`
	NodeID         string      `json:"node_id,omitempty"`
}

type HeartbeatRequest struct {
	ProtocolVersion     string              `json:"protocol_version"`
	DataPlaneID         DataPlaneID         `json:"data_plane_id"`
	ConnectorInstanceID ConnectorInstanceID `json:"connector_instance_id"`
	Capabilities        Capabilities        `json:"capabilities"`
	AgentVersion        string              `json:"agent_version,omitempty"`
}
