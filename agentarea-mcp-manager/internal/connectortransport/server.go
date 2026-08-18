// Package connectortransport adapts the v1 outbound connector protocol to
// ConnectRPC. It deliberately contains no provider construction or listener
// setup: callers mount Handler and inject authentication and dispatchers.
package connectortransport

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"connectrpc.com/connect"
	"github.com/agentarea/mcp-manager/internal/connectorauth"
	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/connectorproto/connectorprotoconnect"
)

const defaultHeartbeatInterval = 30 * time.Second

// ServerConfig supplies the control-plane dependencies for a mounted Connect
// handler. Authenticator is called exactly once, after a syntactically valid
// first Hello and before the logical plane is registered in Hub.
type ServerConfig struct {
	Authenticator     connectorauth.Authenticator
	Hub               *connectorhub.Hub
	HeartbeatInterval time.Duration
	MaxQueuedMessages int
}

func (c ServerConfig) normalized() (ServerConfig, error) {
	if c.Authenticator == nil || c.Hub == nil {
		return ServerConfig{}, errors.New("connector authenticator and hub are required")
	}
	if c.HeartbeatInterval <= 0 {
		c.HeartbeatInterval = defaultHeartbeatInterval
	}
	if c.HeartbeatInterval > time.Hour {
		return ServerConfig{}, errors.New("heartbeat interval exceeds protocol limit")
	}
	if c.MaxQueuedMessages <= 0 {
		c.MaxQueuedMessages = 64
	}
	return c, nil
}

// Server is a ConnectRPC bidi-stream handler. It never logs inbound headers
// or message data, so a bearer credential cannot reach error text or logs.
type Server struct{ cfg ServerConfig }

func NewServer(cfg ServerConfig) (*Server, error) {
	normalized, err := cfg.normalized()
	if err != nil {
		return nil, err
	}
	return &Server{cfg: normalized}, nil
}

func (s *Server) Handler(opts ...connect.HandlerOption) (string, http.Handler) {
	return connectorprotoconnect.NewOutboundConnectorHandler(s, opts...)
}

func (s *Server) Connect(ctx context.Context, stream *connect.BidiStream[connectorproto.ConnectorToControl, connectorproto.ControlToConnector]) error {
	first, err := stream.Receive()
	if err != nil {
		return safeConnectError(connect.CodeInvalidArgument, "connector hello is required")
	}
	if err := connectorproto.ValidateConnectorToControl(first); err != nil {
		return safeConnectError(connect.CodeInvalidArgument, "invalid connector message")
	}
	hello := first.GetHello()
	if hello == nil {
		return safeConnectError(connect.CodeInvalidArgument, "first connector message must be hello")
	}
	credential, ok := bearerCredential(stream.RequestHeader())
	if !ok {
		return safeConnectError(connect.CodeUnauthenticated, "connector authentication failed")
	}
	identity, err := s.cfg.Authenticator.Authenticate(ctx, connectorauth.IncomingConnector{
		Hello: connectorauth.Hello{
			ProtocolVersion:     fmt.Sprint(first.GetProtocolVersion()),
			DataPlaneID:         first.GetDataPlaneId().GetValue(),
			ConnectorInstanceID: first.GetConnectorInstanceId().GetValue(),
			AgentVersion:        hello.GetConnectorVersion(),
			Capabilities:        workloadCapabilities(hello.GetCapabilities()),
		},
		NodeCredential: credential,
	})
	if err != nil || identity.DataPlaneID != first.GetDataPlaneId().GetValue() || identity.ConnectorInstanceID != first.GetConnectorInstanceId().GetValue() {
		return safeConnectError(connect.CodeUnauthenticated, "connector authentication failed")
	}

	sender := &serverSender{stream: stream, maxQueued: s.cfg.MaxQueuedMessages, heartbeatInterval: s.cfg.HeartbeatInterval}
	session, err := s.cfg.Hub.Register(connectorhub.Registration{
		DataPlaneID:         identity.DataPlaneID,
		ConnectorInstanceID: identity.ConnectorInstanceID,
		Capabilities:        hubCapabilities(hello.GetCapabilities()),
		MaxConcurrentOps:    int(hello.GetMaxConcurrentOperations()),
		Sender:              sender,
	})
	if err != nil {
		return safeConnectError(connect.CodeAlreadyExists, "connector already active")
	}
	defer session.Close()
	if err := sender.Send(ctx, connectorhub.Command{DataPlaneID: identity.DataPlaneID, InstanceID: identity.ConnectorInstanceID, Generation: session.Generation(), Kind: "hello_accepted"}); err != nil {
		return safeConnectError(connect.CodeUnavailable, "connector stream unavailable")
	}

	for {
		message, receiveErr := stream.Receive()
		if receiveErr != nil {
			if errors.Is(receiveErr, context.Canceled) {
				return nil
			}
			return receiveErr
		}
		if err := connectorproto.ValidateConnectorToControl(message); err != nil {
			return safeConnectError(connect.CodeInvalidArgument, "invalid connector message")
		}
		if message.GetDataPlaneId().GetValue() != identity.DataPlaneID || message.GetConnectorInstanceId().GetValue() != identity.ConnectorInstanceID {
			return safeConnectError(connect.CodePermissionDenied, "connector identity mismatch")
		}
		if message.GetHello() != nil {
			return safeConnectError(connect.CodeInvalidArgument, "hello is only allowed as the first connector message")
		}
		if err := applyInbound(session, message); err != nil {
			return safeConnectError(connect.CodeInvalidArgument, "invalid connector "+inboundMessageName(message)+" lifecycle message")
		}
	}
}

func inboundMessageName(message *connectorproto.ConnectorToControl) string {
	switch message.GetMessage().(type) {
	case *connectorproto.ConnectorToControl_Heartbeat:
		return "heartbeat"
	case *connectorproto.ConnectorToControl_CapabilityReport:
		return "capability report"
	case *connectorproto.ConnectorToControl_Drain:
		return "drain"
	case *connectorproto.ConnectorToControl_OperationAck:
		return "operation acknowledgment"
	case *connectorproto.ConnectorToControl_OperationResult:
		return "operation result"
	case *connectorproto.ConnectorToControl_ProxyResponseHeaders:
		return "proxy headers"
	case *connectorproto.ConnectorToControl_ProxyResponseChunk:
		return "proxy chunk"
	case *connectorproto.ConnectorToControl_ProxyEnd:
		return "proxy end"
	case *connectorproto.ConnectorToControl_Error:
		return "error"
	default:
		return "unknown"
	}
}

func safeConnectError(code connect.Code, message string) error {
	return connect.NewError(code, errors.New(message))
}

func bearerCredential(headers http.Header) (string, bool) {
	values := headers.Values("Authorization")
	if len(values) != 1 {
		return "", false
	}
	value := values[0]
	if !strings.HasPrefix(value, "Bearer ") {
		return "", false
	}
	credential := strings.TrimPrefix(value, "Bearer ")
	if credential == "" || strings.ContainsAny(credential, "\r\n") {
		return "", false
	}
	return credential, true
}

func applyInbound(session *connectorhub.Session, message *connectorproto.ConnectorToControl) error {
	switch body := message.GetMessage().(type) {
	case *connectorproto.ConnectorToControl_Heartbeat, *connectorproto.ConnectorToControl_Error:
		return nil
	case *connectorproto.ConnectorToControl_CapabilityReport:
		capabilities := hubCapabilities(body.CapabilityReport.GetCapabilities())
		return session.SetCapabilities(capabilities, int(body.CapabilityReport.GetMaxConcurrentOperations()))
	case *connectorproto.ConnectorToControl_Drain:
		return session.SetDraining(true)
	case *connectorproto.ConnectorToControl_OperationAck:
		rejection := ""
		if body.OperationAck.GetRejection() != nil {
			rejection = body.OperationAck.GetRejection().GetMessage()
		}
		return session.Ack(body.OperationAck.GetOperationId().GetValue(), body.OperationAck.GetAccepted(), rejection)
	case *connectorproto.ConnectorToControl_OperationResult:
		return session.Result(connectorhub.OperationResult{
			ID: body.OperationResult.GetOperationId().GetValue(), Status: resultStatus(body.OperationResult.GetStatus()),
			Payload: body.OperationResult.GetResponsePayload(), Error: protoError(body.OperationResult.GetError()),
		})
	case *connectorproto.ConnectorToControl_ProxyResponseHeaders:
		return session.ProxyHeaders(body.ProxyResponseHeaders.GetRequestId().GetValue(), connectorhub.ProxyResponseHeaders{StatusCode: int(body.ProxyResponseHeaders.GetStatusCode()), Headers: fromProtoHeaders(body.ProxyResponseHeaders.GetHeaders())})
	case *connectorproto.ConnectorToControl_ProxyResponseChunk:
		return session.ProxyChunk(body.ProxyResponseChunk.GetRequestId().GetValue(), body.ProxyResponseChunk.GetSequence(), body.ProxyResponseChunk.GetData())
	case *connectorproto.ConnectorToControl_ProxyEnd:
		return session.ProxyEnd(body.ProxyEnd.GetRequestId().GetValue(), proxyReason(body.ProxyEnd.GetReason()))
	default:
		return errors.New("unsupported connector message")
	}
}

func hubCapabilities(capabilities []connectorproto.Capability) []connectorhub.Capability {
	result := make([]connectorhub.Capability, 0, 2)
	for _, capability := range capabilities {
		switch capability {
		case connectorproto.Capability_CAPABILITY_OPERATIONS:
			result = append(result, connectorhub.CapabilityOperations)
		case connectorproto.Capability_CAPABILITY_PROXY:
			result = append(result, connectorhub.CapabilityProxy)
		}
	}
	return result
}

func workloadCapabilities(capabilities []connectorproto.Capability) map[string]bool {
	result := map[string]bool{"mcp": false, "sandbox": false}
	for _, capability := range capabilities {
		switch capability {
		case connectorproto.Capability_CAPABILITY_MCP:
			result["mcp"] = true
		case connectorproto.Capability_CAPABILITY_SANDBOX:
			result["sandbox"] = true
		}
	}
	return result
}

type serverSender struct {
	stream            *connect.BidiStream[connectorproto.ConnectorToControl, connectorproto.ControlToConnector]
	mu                sync.Mutex
	maxQueued         int
	heartbeatInterval time.Duration
}

func (s *serverSender) Send(_ context.Context, command connectorhub.Command) error {
	message, err := controlMessage(command, s.heartbeatInterval)
	if err != nil {
		return err
	}
	if err := connectorproto.ValidateControlToConnector(message); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.stream.Send(message)
}
