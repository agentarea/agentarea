// SPDX-License-Identifier: Apache-2.0

package connectorproto

import (
	"encoding/json"
	"strings"
	"testing"

	"google.golang.org/protobuf/proto"
)

func TestValidV1Envelopes(t *testing.T) {
	connectorPayloads := []isConnectorToControl_Message{
		&ConnectorToControl_Hello{Hello: &Hello{ConnectorVersion: "1.0.0"}},
		&ConnectorToControl_Heartbeat{Heartbeat: &Heartbeat{SentAtUnixMillis: 1}},
		&ConnectorToControl_CapabilityReport{CapabilityReport: &CapabilityReport{Capabilities: []Capability{Capability_CAPABILITY_OPERATIONS, Capability_CAPABILITY_PROXY}, MaxConcurrentOperations: 2}},
		&ConnectorToControl_Drain{Drain: &Drain{Reason: DrainReason_DRAIN_REASON_MAINTENANCE, DeadlineUnixMillis: 1}},
		&ConnectorToControl_Error{Error: validError()},
		&ConnectorToControl_OperationAck{OperationAck: &OperationAck{OperationId: operationID(), Accepted: true}},
		&ConnectorToControl_OperationResult{OperationResult: &OperationResult{OperationId: operationID(), Status: OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED, ResponsePayload: []byte(`{"ok":true}`), ContentType: "application/json"}},
		&ConnectorToControl_ProxyResponseHeaders{ProxyResponseHeaders: &ProxyResponseHeaders{RequestId: requestID(), StatusCode: 200, Headers: []*Header{{Name: "Content-Type", Value: "application/json"}}}},
		&ConnectorToControl_ProxyResponseChunk{ProxyResponseChunk: &ProxyResponseChunk{RequestId: requestID(), Data: []byte("response")}},
		&ConnectorToControl_ProxyEnd{ProxyEnd: &ProxyEnd{RequestId: requestID(), Reason: ProxyEndReason_PROXY_END_REASON_COMPLETE}},
	}
	for _, payload := range connectorPayloads {
		if err := ValidateConnectorToControl(connectorEnvelope(payload)); err != nil {
			t.Fatalf("ValidateConnectorToControl(%T) = %v", payload, err)
		}
	}

	controlPayloads := []isControlToConnector_Message{
		&ControlToConnector_HelloAccepted{HelloAccepted: &HelloAccepted{SelectedProtocolVersion: ProtocolVersionV1, HeartbeatIntervalMillis: 1_000}},
		&ControlToConnector_Heartbeat{Heartbeat: &Heartbeat{SentAtUnixMillis: 1}},
		&ControlToConnector_Drain{Drain: &Drain{Reason: DrainReason_DRAIN_REASON_MAINTENANCE, DeadlineUnixMillis: 1}},
		&ControlToConnector_Error{Error: validError()},
		&ControlToConnector_OperationStart{OperationStart: &OperationStart{OperationId: operationID(), Kind: OperationKind_OPERATION_KIND_MCP_CREATE, DeadlineUnixMillis: 1, RequestPayload: []byte(`{"name":"catalog"}`), ContentType: "application/json"}},
		&ControlToConnector_OperationCancel{OperationCancel: &OperationCancel{OperationId: operationID(), Reason: "operator requested"}},
		&ControlToConnector_ProxyStart{ProxyStart: &ProxyStart{RequestId: requestID(), Method: "POST", TargetPath: "/mcp?session=public", Headers: []*Header{{Name: "Accept", Value: "application/json"}}, DeadlineUnixMillis: 1}},
		&ControlToConnector_ProxyRequestChunk{ProxyRequestChunk: &ProxyRequestChunk{RequestId: requestID(), Data: []byte("request")}},
		&ControlToConnector_ProxyRequestEnd{ProxyRequestEnd: &ProxyRequestEnd{RequestId: requestID(), Reason: ProxyEndReason_PROXY_END_REASON_COMPLETE}},
	}
	for _, payload := range controlPayloads {
		if err := ValidateControlToConnector(controlEnvelope(payload)); err != nil {
			t.Fatalf("ValidateControlToConnector(%T) = %v", payload, err)
		}
	}
}

func TestProviderlessHelloAndCapabilityReportAreValid(t *testing.T) {
	for _, payload := range []isConnectorToControl_Message{
		&ConnectorToControl_Hello{Hello: &Hello{ConnectorVersion: "1.0.0"}},
		&ConnectorToControl_CapabilityReport{CapabilityReport: &CapabilityReport{}},
	} {
		if err := ValidateConnectorToControl(connectorEnvelope(payload)); err != nil {
			t.Fatalf("providerless %T rejected: %v", payload, err)
		}
	}
}

func TestEnvelopeRequiresVersionAndStableIDs(t *testing.T) {
	tests := []struct {
		name string
		edit func(*ConnectorToControl)
		want string
	}{
		{
			name: "version",
			edit: func(envelope *ConnectorToControl) { envelope.ProtocolVersion = 0 },
			want: "protocol_version",
		},
		{
			name: "data plane ID",
			edit: func(envelope *ConnectorToControl) { envelope.DataPlaneId = nil },
			want: "data_plane_id",
		},
		{
			name: "connector ID",
			edit: func(envelope *ConnectorToControl) {
				envelope.ConnectorInstanceId = &ConnectorInstanceID{Value: "not stable"}
			},
			want: "connector_instance_id",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			envelope := connectorEnvelope(&ConnectorToControl_Hello{Hello: &Hello{ConnectorVersion: "1.0.0"}})
			test.edit(envelope)
			mustFail(t, ValidateConnectorToControl(envelope), test.want)
		})
	}
}

func TestEnvelopePayloadExclusivity(t *testing.T) {
	mustFail(t, ValidateConnectorToControl(connectorEnvelope(nil)), "exactly one")
	mustFail(t, ValidateConnectorToControl(connectorEnvelope(&ConnectorToControl_Hello{})), "hello is required")

	hello, err := proto.Marshal(connectorEnvelope(&ConnectorToControl_Hello{Hello: &Hello{ConnectorVersion: "1.0.0"}}))
	if err != nil {
		t.Fatal(err)
	}
	heartbeat, err := proto.Marshal(connectorEnvelope(&ConnectorToControl_Heartbeat{Heartbeat: &Heartbeat{SentAtUnixMillis: 1}}))
	if err != nil {
		t.Fatal(err)
	}
	_, err = DecodeConnectorToControl(append(hello, heartbeat...))
	mustFail(t, err, "exactly one payload")
}

func TestDecodeRejectsMalformedAndUnknownEnvelopes(t *testing.T) {
	_, err := DecodeConnectorToControl([]byte{0x0a})
	mustFail(t, err, "malformed envelope field")

	encoded, err := proto.Marshal(connectorEnvelope(&ConnectorToControl_Hello{Hello: &Hello{ConnectorVersion: "1.0.0"}}))
	if err != nil {
		t.Fatal(err)
	}
	_, err = DecodeConnectorToControl(append(encoded, 0xa0, 0x06, 0x01)) // field 100, varint 1
	mustFail(t, err, "unknown fields")
}

func TestBoundedProxyPayloads(t *testing.T) {
	overChunk := make([]byte, MaxChunkBytes+1)
	mustFail(t, ValidateControlToConnector(controlEnvelope(&ControlToConnector_ProxyRequestChunk{ProxyRequestChunk: &ProxyRequestChunk{RequestId: requestID(), Data: overChunk}})), "exceeds")

	overEnvelope := make([]byte, MaxEnvelopeBytes+1)
	_, err := DecodeConnectorToControl(overEnvelope)
	mustFail(t, err, "exceeds")

	headers := make([]*Header, MaxHeaders+1)
	for index := range headers {
		headers[index] = &Header{Name: "X-Trace", Value: "ok"}
	}
	mustFail(t, ValidateControlToConnector(controlEnvelope(&ControlToConnector_ProxyStart{ProxyStart: &ProxyStart{RequestId: requestID(), Method: "GET", TargetPath: "/", Headers: headers, DeadlineUnixMillis: 1}})), "headers exceed")
}

func TestOperationPayloadsRoundTrip(t *testing.T) {
	requestPayload, err := json.Marshal(map[string]any{"instance_id": "mcp-1", "image": "ghcr.io/agentarea/mcp:latest"})
	if err != nil {
		t.Fatal(err)
	}
	start := controlEnvelope(&ControlToConnector_OperationStart{OperationStart: &OperationStart{
		OperationId:        operationID(),
		Kind:               OperationKind_OPERATION_KIND_MCP_CREATE,
		DeadlineUnixMillis: 1,
		RequestPayload:     requestPayload,
		ContentType:        "application/json; charset=utf-8",
	}})
	encodedStart, err := proto.Marshal(start)
	if err != nil {
		t.Fatal(err)
	}
	decodedStart, err := DecodeControlToConnector(encodedStart)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(decodedStart.GetOperationStart().GetRequestPayload()); got != string(requestPayload) {
		t.Fatalf("request payload = %s, want %s", got, requestPayload)
	}

	responsePayload, err := json.Marshal(map[string]any{"instance_id": "mcp-1", "state": "ready"})
	if err != nil {
		t.Fatal(err)
	}
	result := connectorEnvelope(&ConnectorToControl_OperationResult{OperationResult: &OperationResult{
		OperationId:     operationID(),
		Status:          OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED,
		ResponsePayload: responsePayload,
		ContentType:     "application/json",
	}})
	encodedResult, err := proto.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	decodedResult, err := DecodeConnectorToControl(encodedResult)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(decodedResult.GetOperationResult().GetResponsePayload()); got != string(responsePayload) {
		t.Fatalf("response payload = %s, want %s", got, responsePayload)
	}
}

func TestOperationPayloadBoundsContentTypeAndCredentials(t *testing.T) {
	mustFail(t, ValidateControlToConnector(controlEnvelope(&ControlToConnector_OperationStart{OperationStart: &OperationStart{
		OperationId: operationID(), Kind: OperationKind_OPERATION_KIND_MCP_CREATE, DeadlineUnixMillis: 1,
	}})), "request_payload is required")

	oversized := make([]byte, MaxOperationRequestBytes+1)
	mustFail(t, ValidateControlToConnector(controlEnvelope(&ControlToConnector_OperationStart{OperationStart: &OperationStart{
		OperationId: operationID(), Kind: OperationKind_OPERATION_KIND_MCP_CREATE, DeadlineUnixMillis: 1, RequestPayload: oversized, ContentType: "application/json",
	}})), "exceeds")

	mustFail(t, ValidateControlToConnector(controlEnvelope(&ControlToConnector_OperationStart{OperationStart: &OperationStart{
		OperationId: operationID(), Kind: OperationKind_OPERATION_KIND_MCP_CREATE, DeadlineUnixMillis: 1, RequestPayload: []byte(`{}`), ContentType: "text/plain",
	}})), "application/json")

	mustFail(t, ValidateControlToConnector(controlEnvelope(&ControlToConnector_OperationStart{OperationStart: &OperationStart{
		OperationId: operationID(), Kind: OperationKind_OPERATION_KIND_MCP_CREATE, DeadlineUnixMillis: 1, RequestPayload: []byte(`{"api_key":"not-allowed"}`), ContentType: "application/json",
	}})), "credential-like")
}

func TestStreamingPOSTRequestFlow(t *testing.T) {
	validator := NewStreamValidator()
	start := controlEnvelope(&ControlToConnector_ProxyStart{ProxyStart: &ProxyStart{
		RequestId: requestID(), Method: "POST", TargetPath: "/mcp", Headers: []*Header{{Name: "Content-Type", Value: "application/json"}}, DeadlineUnixMillis: 1,
	}})
	if err := validator.ValidateControl(roundTripControl(t, start)); err != nil {
		t.Fatal(err)
	}
	requestChunk := controlEnvelope(&ControlToConnector_ProxyRequestChunk{ProxyRequestChunk: &ProxyRequestChunk{RequestId: requestID(), Sequence: 0, Data: []byte(`{"jsonrpc":"2.0"}`)}})
	if err := validator.ValidateControl(roundTripControl(t, requestChunk)); err != nil {
		t.Fatal(err)
	}
	if err := validator.ValidateControl(roundTripControl(t, controlEnvelope(&ControlToConnector_ProxyRequestEnd{ProxyRequestEnd: &ProxyRequestEnd{RequestId: requestID(), Reason: ProxyEndReason_PROXY_END_REASON_COMPLETE}}))); err != nil {
		t.Fatal(err)
	}
	responseHeaders := connectorEnvelope(&ConnectorToControl_ProxyResponseHeaders{ProxyResponseHeaders: &ProxyResponseHeaders{
		RequestId: requestID(), StatusCode: 200, Headers: []*Header{{Name: "Content-Type", Value: "application/json"}},
	}})
	if err := validator.ValidateConnector(roundTripConnector(t, responseHeaders)); err != nil {
		t.Fatal(err)
	}
	responseChunk := connectorEnvelope(&ConnectorToControl_ProxyResponseChunk{ProxyResponseChunk: &ProxyResponseChunk{
		RequestId: requestID(), Sequence: 0, Data: []byte(`{"result":{}}`),
	}})
	if err := validator.ValidateConnector(roundTripConnector(t, responseChunk)); err != nil {
		t.Fatal(err)
	}
	responseEnd := connectorEnvelope(&ConnectorToControl_ProxyEnd{ProxyEnd: &ProxyEnd{RequestId: requestID(), Reason: ProxyEndReason_PROXY_END_REASON_COMPLETE}})
	if err := validator.ValidateConnector(roundTripConnector(t, responseEnd)); err != nil {
		t.Fatal(err)
	}
}

func TestStreamingPOSTRejectsOutOfOrderChunks(t *testing.T) {
	validator := NewStreamValidator()
	if err := validator.ValidateControl(controlEnvelope(&ControlToConnector_ProxyStart{ProxyStart: &ProxyStart{RequestId: requestID(), Method: "POST", TargetPath: "/mcp", DeadlineUnixMillis: 1}})); err != nil {
		t.Fatal(err)
	}
	err := validator.ValidateControl(controlEnvelope(&ControlToConnector_ProxyRequestChunk{ProxyRequestChunk: &ProxyRequestChunk{RequestId: requestID(), Sequence: 1, Data: []byte("late")}}))
	mustFail(t, err, "sequence 1, want 0")
}

func TestCredentialLikeHeadersAreForbidden(t *testing.T) {
	for _, header := range []*Header{
		{Name: "Authorization", Value: "Bearer no-secret-here"},
		{Name: "X-Trace", Value: "Bearer no-secret-here"},
		{Name: "X-Api-Key", Value: "opaque"},
	} {
		envelope := controlEnvelope(&ControlToConnector_ProxyStart{ProxyStart: &ProxyStart{
			RequestId:          requestID(),
			Method:             "GET",
			TargetPath:         "/",
			Headers:            []*Header{header},
			DeadlineUnixMillis: 1,
		}})
		mustFail(t, ValidateControlToConnector(envelope), "credential-like")
	}
}

func connectorEnvelope(message isConnectorToControl_Message) *ConnectorToControl {
	return &ConnectorToControl{
		ProtocolVersion:     ProtocolVersionV1,
		DataPlaneId:         &DataPlaneID{Value: "dp-1"},
		ConnectorInstanceId: &ConnectorInstanceID{Value: "connector-1"},
		Message:             message,
	}
}

func controlEnvelope(message isControlToConnector_Message) *ControlToConnector {
	return &ControlToConnector{
		ProtocolVersion:     ProtocolVersionV1,
		DataPlaneId:         &DataPlaneID{Value: "dp-1"},
		ConnectorInstanceId: &ConnectorInstanceID{Value: "connector-1"},
		Message:             message,
	}
}

func operationID() *OperationID { return &OperationID{Value: "operation-1"} }

func requestID() *RequestID { return &RequestID{Value: "request-1"} }

func validError() *Error {
	return &Error{Code: ErrorCode_ERROR_CODE_INTERNAL, Message: "internal failure"}
}

func roundTripControl(t *testing.T, envelope *ControlToConnector) *ControlToConnector {
	t.Helper()
	encoded, err := proto.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeControlToConnector(encoded)
	if err != nil {
		t.Fatal(err)
	}
	return decoded
}

func roundTripConnector(t *testing.T, envelope *ConnectorToControl) *ConnectorToControl {
	t.Helper()
	encoded, err := proto.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeConnectorToControl(encoded)
	if err != nil {
		t.Fatal(err)
	}
	return decoded
}

func mustFail(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("error = %v, want it to contain %q", err, want)
	}
}
