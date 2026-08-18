package connectortransport

import (
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
)

func controlMessage(command connectorhub.Command, heartbeatInterval time.Duration) (*connectorproto.ControlToConnector, error) {
	base := func() *connectorproto.ControlToConnector {
		return &connectorproto.ControlToConnector{ProtocolVersion: connectorproto.ProtocolVersionV1, DataPlaneId: &connectorproto.DataPlaneID{Value: command.DataPlaneID}, ConnectorInstanceId: &connectorproto.ConnectorInstanceID{Value: command.InstanceID}}
	}
	message := base()
	switch command.Kind {
	case "hello_accepted":
		message.Message = &connectorproto.ControlToConnector_HelloAccepted{HelloAccepted: &connectorproto.HelloAccepted{SelectedProtocolVersion: connectorproto.ProtocolVersionV1, HeartbeatIntervalMillis: uint32(heartbeatInterval.Milliseconds())}}
	case connectorhub.CommandOperationStart:
		if command.Operation == nil {
			return nil, fmt.Errorf("operation start is required")
		}
		kind, err := operationKind(command.Operation.Kind)
		if err != nil {
			return nil, err
		}
		message.Message = &connectorproto.ControlToConnector_OperationStart{OperationStart: &connectorproto.OperationStart{OperationId: &connectorproto.OperationID{Value: command.Operation.ID}, Kind: kind, DeadlineUnixMillis: command.Operation.DeadlineUnixMilli, RequestPayload: append([]byte(nil), command.Operation.Payload...), ContentType: command.Operation.ContentType}}
	case connectorhub.CommandOperationCancel:
		if command.Cancel == nil {
			return nil, fmt.Errorf("operation cancel is required")
		}
		message.Message = &connectorproto.ControlToConnector_OperationCancel{OperationCancel: &connectorproto.OperationCancel{OperationId: &connectorproto.OperationID{Value: command.Cancel.ID}, Reason: command.Cancel.Reason}}
	case connectorhub.CommandProxyStart:
		if command.Proxy == nil {
			return nil, fmt.Errorf("proxy start is required")
		}
		message.Message = &connectorproto.ControlToConnector_ProxyStart{ProxyStart: &connectorproto.ProxyStart{RequestId: &connectorproto.RequestID{Value: command.Proxy.ID}, Method: command.Proxy.Method, TargetPath: command.Proxy.Path, Headers: toProtoHeaders(command.Proxy.Headers), DeadlineUnixMillis: command.Proxy.DeadlineUnixMilli}}
	case connectorhub.CommandProxyChunk:
		if command.Chunk == nil {
			return nil, fmt.Errorf("proxy request chunk is required")
		}
		message.Message = &connectorproto.ControlToConnector_ProxyRequestChunk{ProxyRequestChunk: &connectorproto.ProxyRequestChunk{RequestId: &connectorproto.RequestID{Value: command.Chunk.ID}, Sequence: command.Chunk.Sequence, Data: append([]byte(nil), command.Chunk.Data...)}}
	case connectorhub.CommandProxyEnd:
		if command.ProxyEnd == nil {
			return nil, fmt.Errorf("proxy request end is required")
		}
		message.Message = &connectorproto.ControlToConnector_ProxyRequestEnd{ProxyRequestEnd: &connectorproto.ProxyRequestEnd{RequestId: &connectorproto.RequestID{Value: command.ProxyEnd.ID}, Reason: endReason(command.ProxyEnd.Reason)}}
	default:
		return nil, fmt.Errorf("unsupported connector command")
	}
	return message, nil
}

func operationKind(kind string) (connectorproto.OperationKind, error) {
	if number, ok := connectorproto.OperationKind_value[kind]; ok && number != 0 {
		return connectorproto.OperationKind(number), nil
	}
	return connectorproto.OperationKind_OPERATION_KIND_UNSPECIFIED, fmt.Errorf("unsupported operation kind")
}

func resultStatus(status connectorproto.OperationResultStatus) connectorhub.ResultStatus {
	switch status {
	case connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED:
		return connectorhub.ResultSucceeded
	case connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_FAILED:
		return connectorhub.ResultFailed
	case connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_CANCELLED:
		return connectorhub.ResultCancelled
	case connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_DEADLINE_EXCEEDED:
		return connectorhub.ResultDeadlineExceeded
	default:
		return ""
	}
}

func protoError(value *connectorproto.Error) string {
	if value == nil {
		return ""
	}
	switch value.GetCode() {
	case connectorproto.ErrorCode_ERROR_CODE_NOT_FOUND:
		return "not_found"
	case connectorproto.ErrorCode_ERROR_CODE_PERMISSION_DENIED:
		return "permission_denied"
	}
	return value.GetMessage()
}

func toProtoHeaders(headers []connectorhub.Header) []*connectorproto.Header {
	result := make([]*connectorproto.Header, 0, len(headers))
	for _, header := range headers {
		result = append(result, &connectorproto.Header{Name: header.Name, Value: header.Value})
	}
	return result
}

func fromProtoHeaders(headers []*connectorproto.Header) []connectorhub.Header {
	result := make([]connectorhub.Header, 0, len(headers))
	for _, header := range headers {
		result = append(result, connectorhub.Header{Name: header.GetName(), Value: header.GetValue()})
	}
	return result
}

func endReason(reason string) connectorproto.ProxyEndReason {
	switch reason {
	case "complete":
		return connectorproto.ProxyEndReason_PROXY_END_REASON_COMPLETE
	case "cancelled":
		return connectorproto.ProxyEndReason_PROXY_END_REASON_CANCELLED
	case "deadline_exceeded":
		return connectorproto.ProxyEndReason_PROXY_END_REASON_DEADLINE_EXCEEDED
	default:
		return connectorproto.ProxyEndReason_PROXY_END_REASON_ERROR
	}
}

func proxyReason(reason connectorproto.ProxyEndReason) string {
	switch reason {
	case connectorproto.ProxyEndReason_PROXY_END_REASON_COMPLETE:
		return "complete"
	case connectorproto.ProxyEndReason_PROXY_END_REASON_CANCELLED:
		return "cancelled"
	case connectorproto.ProxyEndReason_PROXY_END_REASON_DEADLINE_EXCEEDED:
		return "deadline_exceeded"
	default:
		return "error"
	}
}
