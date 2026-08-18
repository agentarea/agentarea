// SPDX-License-Identifier: Apache-2.0

// Package connectorproto contains the v1 outbound connector wire contract and
// strict validation that callers must run before dispatching a stream message.
package connectorproto

import (
	"encoding/json"
	"fmt"
	"mime"
	"net/url"
	"strings"
	"sync"

	"google.golang.org/protobuf/encoding/protowire"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

const (
	ProtocolVersionV1 uint32 = 1

	MaxEnvelopeBytes           = 1 << 20 // 1 MiB
	MaxChunkBytes              = 256 << 10
	MaxStableIDBytes           = 128
	MaxConnectorVersionBytes   = 128
	MaxCapabilities            = 32
	MaxConcurrentOperations    = 10_000
	MaxHeartbeatIntervalMillis = 3_600_000
	MaxErrorMessageBytes       = 4 << 10
	MaxCancelReasonBytes       = 1 << 10
	MaxOperationRequestBytes   = 256 << 10
	MaxOperationResponseBytes  = 256 << 10
	MaxContentTypeBytes        = 128
	MaxHeaders                 = 64
	MaxHeaderNameBytes         = 128
	MaxHeaderValueBytes        = 4 << 10
	MaxMethodBytes             = 16
	MaxTargetPathBytes         = 8 << 10
)

// DecodeConnectorToControl unmarshals and validates a connector-originated
// envelope. Use it at a stream boundary before passing a message to handlers.
func DecodeConnectorToControl(data []byte) (*ConnectorToControl, error) {
	if len(data) > MaxEnvelopeBytes {
		return nil, fmt.Errorf("connector envelope exceeds %d bytes", MaxEnvelopeBytes)
	}
	if err := requireExactlyOneRawPayload(data, connectorPayloadFields); err != nil {
		return nil, fmt.Errorf("decode connector envelope: %w", err)
	}

	envelope := new(ConnectorToControl)
	if err := (proto.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(data, envelope); err != nil {
		return nil, fmt.Errorf("decode connector envelope: %w", err)
	}
	if err := ValidateConnectorToControl(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

// DecodeControlToConnector unmarshals and validates a control-plane-originated
// envelope. Use it at a stream boundary before passing a message to handlers.
func DecodeControlToConnector(data []byte) (*ControlToConnector, error) {
	if len(data) > MaxEnvelopeBytes {
		return nil, fmt.Errorf("control envelope exceeds %d bytes", MaxEnvelopeBytes)
	}
	if err := requireExactlyOneRawPayload(data, controlPayloadFields); err != nil {
		return nil, fmt.Errorf("decode control envelope: %w", err)
	}

	envelope := new(ControlToConnector)
	if err := (proto.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(data, envelope); err != nil {
		return nil, fmt.Errorf("decode control envelope: %w", err)
	}
	if err := ValidateControlToConnector(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

// ValidateConnectorToControl validates a constructed connector-originated
// envelope. It rejects absent or invalid oneof payloads, unknown fields, and
// values outside the v1 resource bounds.
func ValidateConnectorToControl(envelope *ConnectorToControl) error {
	if envelope == nil {
		return fmt.Errorf("connector envelope is required")
	}
	if err := validateEnvelopeBase(envelope.GetProtocolVersion(), envelope.GetDataPlaneId(), envelope.GetConnectorInstanceId(), proto.Size(envelope)); err != nil {
		return err
	}
	if err := rejectUnknownFields(envelope.ProtoReflect(), "connector envelope"); err != nil {
		return err
	}

	switch message := envelope.GetMessage().(type) {
	case *ConnectorToControl_Hello:
		return validateHello(message.Hello)
	case *ConnectorToControl_Heartbeat:
		return validateHeartbeat(message.Heartbeat)
	case *ConnectorToControl_CapabilityReport:
		return validateCapabilityReport(message.CapabilityReport)
	case *ConnectorToControl_Drain:
		return validateDrain(message.Drain)
	case *ConnectorToControl_Error:
		return validateError(message.Error)
	case *ConnectorToControl_OperationAck:
		return validateOperationAck(message.OperationAck)
	case *ConnectorToControl_OperationResult:
		return validateOperationResult(message.OperationResult)
	case *ConnectorToControl_ProxyResponseHeaders:
		return validateProxyResponseHeaders(message.ProxyResponseHeaders)
	case *ConnectorToControl_ProxyResponseChunk:
		return validateProxyResponseChunk(message.ProxyResponseChunk)
	case *ConnectorToControl_ProxyEnd:
		return validateProxyEnd(message.ProxyEnd)
	default:
		return fmt.Errorf("connector envelope must contain exactly one supported message")
	}
}

// ValidateControlToConnector validates a constructed control-plane-originated
// envelope before it is written to a connector stream.
func ValidateControlToConnector(envelope *ControlToConnector) error {
	if envelope == nil {
		return fmt.Errorf("control envelope is required")
	}
	if err := validateEnvelopeBase(envelope.GetProtocolVersion(), envelope.GetDataPlaneId(), envelope.GetConnectorInstanceId(), proto.Size(envelope)); err != nil {
		return err
	}
	if err := rejectUnknownFields(envelope.ProtoReflect(), "control envelope"); err != nil {
		return err
	}

	switch message := envelope.GetMessage().(type) {
	case *ControlToConnector_HelloAccepted:
		return validateHelloAccepted(message.HelloAccepted)
	case *ControlToConnector_Heartbeat:
		return validateHeartbeat(message.Heartbeat)
	case *ControlToConnector_Drain:
		return validateDrain(message.Drain)
	case *ControlToConnector_Error:
		return validateError(message.Error)
	case *ControlToConnector_OperationStart:
		return validateOperationStart(message.OperationStart)
	case *ControlToConnector_OperationCancel:
		return validateOperationCancel(message.OperationCancel)
	case *ControlToConnector_ProxyStart:
		return validateProxyStart(message.ProxyStart)
	case *ControlToConnector_ProxyRequestChunk:
		return validateProxyRequestChunk(message.ProxyRequestChunk)
	case *ControlToConnector_ProxyRequestEnd:
		return validateProxyRequestEnd(message.ProxyRequestEnd)
	default:
		return fmt.Errorf("control envelope must contain exactly one supported message")
	}
}

func validateEnvelopeBase(version uint32, dataPlaneID *DataPlaneID, connectorID *ConnectorInstanceID, encodedSize int) error {
	if encodedSize > MaxEnvelopeBytes {
		return fmt.Errorf("envelope exceeds %d bytes", MaxEnvelopeBytes)
	}
	if version != ProtocolVersionV1 {
		return fmt.Errorf("protocol_version must be %d", ProtocolVersionV1)
	}
	if dataPlaneID == nil {
		return fmt.Errorf("data_plane_id is required")
	}
	if err := validateStableID("data_plane_id", dataPlaneID.GetValue()); err != nil {
		return err
	}
	if connectorID == nil {
		return fmt.Errorf("connector_instance_id is required")
	}
	return validateStableID("connector_instance_id", connectorID.GetValue())
}

func validateHello(message *Hello) error {
	if message == nil {
		return fmt.Errorf("hello is required")
	}
	if err := validateRequiredText("hello.connector_version", message.GetConnectorVersion(), MaxConnectorVersionBytes); err != nil {
		return err
	}
	return validateCapabilities("hello", message.GetCapabilities(), message.GetMaxConcurrentOperations())
}

func validateHelloAccepted(message *HelloAccepted) error {
	if message == nil {
		return fmt.Errorf("hello_accepted is required")
	}
	if message.GetSelectedProtocolVersion() != ProtocolVersionV1 {
		return fmt.Errorf("hello_accepted.selected_protocol_version must be %d", ProtocolVersionV1)
	}
	if message.GetHeartbeatIntervalMillis() == 0 || message.GetHeartbeatIntervalMillis() > MaxHeartbeatIntervalMillis {
		return fmt.Errorf("hello_accepted.heartbeat_interval_millis must be between 1 and %d", MaxHeartbeatIntervalMillis)
	}
	return nil
}

func validateHeartbeat(message *Heartbeat) error {
	if message == nil || message.GetSentAtUnixMillis() <= 0 {
		return fmt.Errorf("heartbeat.sent_at_unix_millis must be positive")
	}
	return nil
}

func validateCapabilityReport(message *CapabilityReport) error {
	if message == nil {
		return fmt.Errorf("capability_report is required")
	}
	return validateCapabilities("capability_report", message.GetCapabilities(), message.GetMaxConcurrentOperations())
}

func validateCapabilities(field string, capabilities []Capability, maxConcurrent uint32) error {
	if len(capabilities) > MaxCapabilities {
		return fmt.Errorf("%s.capabilities exceeds %d entries", field, MaxCapabilities)
	}
	seen := make(map[Capability]struct{}, len(capabilities))
	for _, capability := range capabilities {
		if capability == Capability_CAPABILITY_UNSPECIFIED || !capabilityKnown(capability) {
			return fmt.Errorf("%s contains an unsupported capability", field)
		}
		if _, duplicate := seen[capability]; duplicate {
			return fmt.Errorf("%s contains a duplicate capability", field)
		}
		seen[capability] = struct{}{}
	}
	if maxConcurrent > MaxConcurrentOperations {
		return fmt.Errorf("%s.max_concurrent_operations exceeds %d", field, MaxConcurrentOperations)
	}
	if len(capabilities) == 0 && maxConcurrent != 0 {
		return fmt.Errorf("%s.max_concurrent_operations must be zero without capabilities", field)
	}
	return nil
}

func validateDrain(message *Drain) error {
	if message == nil || !drainReasonKnown(message.GetReason()) {
		return fmt.Errorf("drain.reason is required")
	}
	if message.GetDeadlineUnixMillis() <= 0 {
		return fmt.Errorf("drain.deadline_unix_millis must be positive")
	}
	return nil
}

func validateError(message *Error) error {
	if message == nil {
		return fmt.Errorf("error is required")
	}
	if !errorCodeKnown(message.GetCode()) {
		return fmt.Errorf("error.code is required")
	}
	return validateRequiredText("error.message", message.GetMessage(), MaxErrorMessageBytes)
}

func validateOperationStart(message *OperationStart) error {
	if message == nil {
		return fmt.Errorf("operation_start is required")
	}
	if err := validateOperationID(message.GetOperationId()); err != nil {
		return err
	}
	if !operationKindKnown(message.GetKind()) {
		return fmt.Errorf("operation_start.kind is required")
	}
	if message.GetDeadlineUnixMillis() <= 0 {
		return fmt.Errorf("operation_start.deadline_unix_millis must be positive")
	}
	return validateOperationPayload("operation_start.request_payload", message.GetRequestPayload(), message.GetContentType(), MaxOperationRequestBytes, true)
}

func validateOperationAck(message *OperationAck) error {
	if message == nil {
		return fmt.Errorf("operation_ack is required")
	}
	if err := validateOperationID(message.GetOperationId()); err != nil {
		return err
	}
	if message.GetAccepted() && message.GetRejection() != nil {
		return fmt.Errorf("operation_ack must not include rejection when accepted")
	}
	if !message.GetAccepted() {
		if message.GetRejection() == nil {
			return fmt.Errorf("operation_ack.rejection is required when not accepted")
		}
		return validateError(message.GetRejection())
	}
	return nil
}

func validateOperationResult(message *OperationResult) error {
	if message == nil {
		return fmt.Errorf("operation_result is required")
	}
	if err := validateOperationID(message.GetOperationId()); err != nil {
		return err
	}
	if !operationResultStatusKnown(message.GetStatus()) {
		return fmt.Errorf("operation_result.status is required")
	}
	if message.GetStatus() == OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED && message.GetError() != nil {
		return fmt.Errorf("successful operation_result must not include error")
	}
	if message.GetStatus() == OperationResultStatus_OPERATION_RESULT_STATUS_FAILED && message.GetError() == nil {
		return fmt.Errorf("failed operation_result.error is required")
	}
	if message.GetError() != nil {
		if err := validateError(message.GetError()); err != nil {
			return err
		}
	}
	return validateOperationPayload("operation_result.response_payload", message.GetResponsePayload(), message.GetContentType(), MaxOperationResponseBytes, message.GetStatus() == OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED)
}

func validateOperationCancel(message *OperationCancel) error {
	if message == nil {
		return fmt.Errorf("operation_cancel is required")
	}
	if err := validateOperationID(message.GetOperationId()); err != nil {
		return err
	}
	return validateRequiredText("operation_cancel.reason", message.GetReason(), MaxCancelReasonBytes)
}

func validateProxyStart(message *ProxyStart) error {
	if message == nil {
		return fmt.Errorf("proxy_start is required")
	}
	if err := validateRequestID(message.GetRequestId()); err != nil {
		return err
	}
	if len(message.GetMethod()) == 0 || len(message.GetMethod()) > MaxMethodBytes || !isHTTPToken(message.GetMethod()) {
		return fmt.Errorf("proxy_start.method must be an HTTP token no longer than %d bytes", MaxMethodBytes)
	}
	if err := validateTargetPath(message.GetTargetPath()); err != nil {
		return err
	}
	if err := validateHeaders(message.GetHeaders()); err != nil {
		return err
	}
	if message.GetDeadlineUnixMillis() <= 0 {
		return fmt.Errorf("proxy_start.deadline_unix_millis must be positive")
	}
	return nil
}

func validateProxyRequestChunk(message *ProxyRequestChunk) error {
	if message == nil {
		return fmt.Errorf("proxy_request_chunk is required")
	}
	if err := validateRequestID(message.GetRequestId()); err != nil {
		return err
	}
	if len(message.GetData()) > MaxChunkBytes {
		return fmt.Errorf("proxy_request_chunk.data exceeds %d bytes", MaxChunkBytes)
	}
	return nil
}

func validateProxyRequestEnd(message *ProxyRequestEnd) error {
	if message == nil {
		return fmt.Errorf("proxy_request_end is required")
	}
	if err := validateRequestID(message.GetRequestId()); err != nil {
		return err
	}
	if !proxyEndReasonKnown(message.GetReason()) {
		return fmt.Errorf("proxy_request_end.reason is required")
	}
	if message.GetReason() == ProxyEndReason_PROXY_END_REASON_ERROR && message.GetError() == nil {
		return fmt.Errorf("proxy_request_end.error is required when reason is error")
	}
	if message.GetReason() != ProxyEndReason_PROXY_END_REASON_ERROR && message.GetError() != nil {
		return fmt.Errorf("proxy_request_end.error is only allowed when reason is error")
	}
	if message.GetError() != nil {
		return validateError(message.GetError())
	}
	return nil
}

func validateProxyResponseHeaders(message *ProxyResponseHeaders) error {
	if message == nil {
		return fmt.Errorf("proxy_response_headers is required")
	}
	if err := validateRequestID(message.GetRequestId()); err != nil {
		return err
	}
	if message.GetStatusCode() < 100 || message.GetStatusCode() > 599 {
		return fmt.Errorf("proxy_response_headers.status_code must be between 100 and 599")
	}
	return validateHeaders(message.GetHeaders())
}

func validateProxyResponseChunk(message *ProxyResponseChunk) error {
	if message == nil {
		return fmt.Errorf("proxy_response_chunk is required")
	}
	if err := validateRequestID(message.GetRequestId()); err != nil {
		return err
	}
	if len(message.GetData()) > MaxChunkBytes {
		return fmt.Errorf("proxy_response_chunk.data exceeds %d bytes", MaxChunkBytes)
	}
	return nil
}

func validateProxyEnd(message *ProxyEnd) error {
	if message == nil {
		return fmt.Errorf("proxy_end is required")
	}
	if err := validateRequestID(message.GetRequestId()); err != nil {
		return err
	}
	if !proxyEndReasonKnown(message.GetReason()) {
		return fmt.Errorf("proxy_end.reason is required")
	}
	if message.GetReason() == ProxyEndReason_PROXY_END_REASON_ERROR && message.GetError() == nil {
		return fmt.Errorf("proxy_end.error is required when reason is error")
	}
	if message.GetReason() != ProxyEndReason_PROXY_END_REASON_ERROR && message.GetError() != nil {
		return fmt.Errorf("proxy_end.error is only allowed when reason is error")
	}
	if message.GetError() != nil {
		return validateError(message.GetError())
	}
	return nil
}

func validateOperationID(id *OperationID) error {
	if id == nil {
		return fmt.Errorf("operation_id is required")
	}
	return validateStableID("operation_id", id.GetValue())
}

func validateRequestID(id *RequestID) error {
	if id == nil {
		return fmt.Errorf("request_id is required")
	}
	return validateStableID("request_id", id.GetValue())
}

func validateStableID(field, value string) error {
	if len(value) == 0 || len(value) > MaxStableIDBytes {
		return fmt.Errorf("%s must contain between 1 and %d bytes", field, MaxStableIDBytes)
	}
	for index := 0; index < len(value); index++ {
		character := value[index]
		if ('a' <= character && character <= 'z') || ('A' <= character && character <= 'Z') || ('0' <= character && character <= '9') || character == '-' || character == '_' || character == '.' || character == ':' {
			continue
		}
		return fmt.Errorf("%s contains an invalid stable ID character", field)
	}
	return nil
}

func validateRequiredText(field, value string, maxBytes int) error {
	if len(value) == 0 || len(value) > maxBytes {
		return fmt.Errorf("%s must contain between 1 and %d bytes", field, maxBytes)
	}
	if strings.ContainsAny(value, "\r\n") {
		return fmt.Errorf("%s must not contain line breaks", field)
	}
	return nil
}

func validateOperationPayload(field string, payload []byte, contentType string, maxBytes int, required bool) error {
	if len(payload) == 0 {
		if required {
			return fmt.Errorf("%s is required", field)
		}
		if contentType != "" {
			return fmt.Errorf("%s.content_type requires a payload", field)
		}
		return nil
	}
	if len(payload) > maxBytes {
		return fmt.Errorf("%s exceeds %d bytes", field, maxBytes)
	}
	if len(contentType) == 0 || len(contentType) > MaxContentTypeBytes {
		return fmt.Errorf("%s.content_type is required and must be no longer than %d bytes", field, MaxContentTypeBytes)
	}
	mediaType, _, err := mime.ParseMediaType(contentType)
	if err != nil || mediaType != "application/json" {
		return fmt.Errorf("%s.content_type must be application/json", field)
	}
	if !json.Valid(payload) {
		return fmt.Errorf("%s must contain valid JSON", field)
	}
	var decoded any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		return fmt.Errorf("%s must contain valid JSON: %w", field, err)
	}
	if containsCredentialJSONKey(decoded) {
		return fmt.Errorf("credential-like fields are forbidden in %s", field)
	}
	return nil
}

func containsCredentialJSONKey(value any) bool {
	switch typed := value.(type) {
	case map[string]any:
		for key, nested := range typed {
			if isCredentialLikeHeader(key) || containsCredentialJSONKey(nested) {
				return true
			}
		}
	case []any:
		for _, nested := range typed {
			if containsCredentialJSONKey(nested) {
				return true
			}
		}
	case string:
		return containsCredentialValue(typed)
	}
	return false
}

func validateTargetPath(value string) error {
	if len(value) == 0 || len(value) > MaxTargetPathBytes || !strings.HasPrefix(value, "/") {
		return fmt.Errorf("proxy_start.target_path must be an origin-form path no longer than %d bytes", MaxTargetPathBytes)
	}
	parsed, err := url.ParseRequestURI(value)
	if err != nil || parsed.IsAbs() || parsed.Host != "" || parsed.User != nil {
		return fmt.Errorf("proxy_start.target_path must not contain an authority or credentials")
	}
	return nil
}

func validateHeaders(headers []*Header) error {
	if len(headers) > MaxHeaders {
		return fmt.Errorf("headers exceed %d entries", MaxHeaders)
	}
	for _, header := range headers {
		if header == nil {
			return fmt.Errorf("headers must not contain nil entries")
		}
		if len(header.GetName()) == 0 || len(header.GetName()) > MaxHeaderNameBytes || !isHTTPToken(header.GetName()) {
			return fmt.Errorf("header name must be an HTTP token no longer than %d bytes", MaxHeaderNameBytes)
		}
		if len(header.GetValue()) > MaxHeaderValueBytes || strings.ContainsAny(header.GetValue(), "\r\n") {
			return fmt.Errorf("header value exceeds %d bytes or contains a line break", MaxHeaderValueBytes)
		}
		if isCredentialLikeHeader(header.GetName()) || containsCredentialValue(header.GetValue()) {
			return fmt.Errorf("credential-like headers are forbidden in connector message bodies")
		}
	}
	return nil
}

func isHTTPToken(value string) bool {
	if value == "" {
		return false
	}
	for index := 0; index < len(value); index++ {
		character := value[index]
		if character <= 32 || character >= 127 || strings.ContainsRune("()<>@,;:\\\"/[]?={} \t", rune(character)) {
			return false
		}
	}
	return true
}

func isCredentialLikeHeader(name string) bool {
	canonical := strings.NewReplacer("-", "", "_", "").Replace(strings.ToLower(name))
	switch canonical {
	case "authorization", "proxyauthorization", "cookie", "setcookie", "apikey", "xapikey", "authtoken", "xauthtoken", "accesstoken", "xaccesstoken", "authentication":
		return true
	}
	return strings.Contains(canonical, "credential") || strings.Contains(canonical, "secret") || strings.Contains(canonical, "password") || strings.Contains(canonical, "token")
}

func containsCredentialValue(value string) bool {
	lower := strings.ToLower(value)
	return strings.HasPrefix(lower, "bearer ") || strings.HasPrefix(lower, "basic ") || strings.Contains(lower, "api_key=") || strings.Contains(lower, "apikey=") || strings.Contains(lower, "token=") || strings.Contains(lower, "password=") || strings.Contains(lower, "secret=")
}

func operationKindKnown(value OperationKind) bool {
	return value >= OperationKind_OPERATION_KIND_MCP_CREATE && value <= OperationKind_OPERATION_KIND_SANDBOX_TASK_RETIRE
}

func operationResultStatusKnown(value OperationResultStatus) bool {
	return value >= OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED && value <= OperationResultStatus_OPERATION_RESULT_STATUS_DEADLINE_EXCEEDED
}

func errorCodeKnown(value ErrorCode) bool {
	return value >= ErrorCode_ERROR_CODE_INVALID_ARGUMENT && value <= ErrorCode_ERROR_CODE_PERMISSION_DENIED
}

func drainReasonKnown(value DrainReason) bool {
	return value >= DrainReason_DRAIN_REASON_MAINTENANCE && value <= DrainReason_DRAIN_REASON_CAPACITY
}

func capabilityKnown(value Capability) bool {
	return value >= Capability_CAPABILITY_OPERATIONS && value <= Capability_CAPABILITY_SANDBOX
}

func proxyEndReasonKnown(value ProxyEndReason) bool {
	return value >= ProxyEndReason_PROXY_END_REASON_COMPLETE && value <= ProxyEndReason_PROXY_END_REASON_ERROR
}

func rejectUnknownFields(message protoreflect.Message, path string) error {
	if len(message.GetUnknown()) != 0 {
		return fmt.Errorf("%s contains unknown fields", path)
	}
	var validationErr error
	message.Range(func(field protoreflect.FieldDescriptor, value protoreflect.Value) bool {
		if validationErr != nil {
			return false
		}
		if field.IsList() && field.Kind() == protoreflect.MessageKind {
			list := value.List()
			for index := 0; index < list.Len(); index++ {
				validationErr = rejectUnknownFields(list.Get(index).Message(), path+"."+string(field.Name()))
				if validationErr != nil {
					return false
				}
			}
			return true
		}
		if field.Kind() == protoreflect.MessageKind {
			validationErr = rejectUnknownFields(value.Message(), path+"."+string(field.Name()))
		}
		return validationErr == nil
	})
	return validationErr
}

var connectorPayloadFields = map[protowire.Number]struct{}{
	10: {}, 11: {}, 12: {}, 13: {}, 14: {}, 15: {}, 16: {}, 18: {}, 19: {}, 20: {},
}

var controlPayloadFields = map[protowire.Number]struct{}{
	10: {}, 11: {}, 12: {}, 13: {}, 14: {}, 15: {}, 16: {}, 17: {}, 18: {},
}

// requireExactlyOneRawPayload closes a protobuf oneof edge case: protobuf
// decoders retain the final oneof value when malformed wire bytes carry more
// than one. The wire contract rejects that ambiguity before dispatch.
func requireExactlyOneRawPayload(data []byte, payloadFields map[protowire.Number]struct{}) error {
	payloadCount := 0
	for len(data) > 0 {
		fieldNumber, fieldType, tagSize := protowire.ConsumeTag(data)
		if tagSize < 0 {
			return fmt.Errorf("malformed envelope tag")
		}
		data = data[tagSize:]
		fieldSize := protowire.ConsumeFieldValue(fieldNumber, fieldType, data)
		if fieldSize < 0 {
			return fmt.Errorf("malformed envelope field")
		}
		if _, isPayload := payloadFields[fieldNumber]; isPayload {
			payloadCount++
		}
		data = data[fieldSize:]
	}
	if payloadCount != 1 {
		return fmt.Errorf("envelope must contain exactly one payload, got %d", payloadCount)
	}
	return nil
}

// StreamValidator applies the v1 per-envelope checks and the ordering rules
// that need stream-local state. It is safe for concurrent use, although a
// single stream should normally be read and written serially.
type StreamValidator struct {
	mu       sync.Mutex
	requests map[string]*proxyRequestState
}

type proxyRequestState struct {
	dataPlaneID  string
	connectorID  string
	nextRequest  uint64
	requestEnded bool
	gotHeaders   bool
	nextResponse uint64
}

// NewStreamValidator returns an empty validator for one bidirectional stream.
func NewStreamValidator() *StreamValidator {
	return &StreamValidator{requests: make(map[string]*proxyRequestState)}
}

// ValidateControl validates a control-to-connector message and records the
// request start, ordered request chunks, and request end for proxy traffic.
func (validator *StreamValidator) ValidateControl(envelope *ControlToConnector) error {
	if err := ValidateControlToConnector(envelope); err != nil {
		return err
	}
	validator.mu.Lock()
	defer validator.mu.Unlock()

	switch message := envelope.GetMessage().(type) {
	case *ControlToConnector_ProxyStart:
		requestID := message.ProxyStart.GetRequestId().GetValue()
		if _, exists := validator.requests[requestID]; exists {
			return fmt.Errorf("proxy request_id %q is already active", requestID)
		}
		validator.requests[requestID] = &proxyRequestState{
			dataPlaneID: envelope.GetDataPlaneId().GetValue(),
			connectorID: envelope.GetConnectorInstanceId().GetValue(),
		}
	case *ControlToConnector_ProxyRequestChunk:
		state, err := validator.proxyState(envelope, message.ProxyRequestChunk.GetRequestId().GetValue())
		if err != nil {
			return err
		}
		if state.requestEnded {
			return fmt.Errorf("proxy request chunk arrived after request end")
		}
		if message.ProxyRequestChunk.GetSequence() != state.nextRequest {
			return fmt.Errorf("proxy request chunk sequence %d, want %d", message.ProxyRequestChunk.GetSequence(), state.nextRequest)
		}
		state.nextRequest++
	case *ControlToConnector_ProxyRequestEnd:
		state, err := validator.proxyState(envelope, message.ProxyRequestEnd.GetRequestId().GetValue())
		if err != nil {
			return err
		}
		if state.requestEnded {
			return fmt.Errorf("duplicate proxy request end")
		}
		state.requestEnded = true
	}
	return nil
}

// ValidateConnector validates a connector-to-control message and records the
// ordered response half for an existing proxy request.
func (validator *StreamValidator) ValidateConnector(envelope *ConnectorToControl) error {
	if err := ValidateConnectorToControl(envelope); err != nil {
		return err
	}
	validator.mu.Lock()
	defer validator.mu.Unlock()

	switch message := envelope.GetMessage().(type) {
	case *ConnectorToControl_ProxyResponseHeaders:
		state, err := validator.proxyState(envelope, message.ProxyResponseHeaders.GetRequestId().GetValue())
		if err != nil {
			return err
		}
		if !state.requestEnded {
			return fmt.Errorf("proxy response headers arrived before request end")
		}
		if state.gotHeaders {
			return fmt.Errorf("duplicate proxy response headers")
		}
		state.gotHeaders = true
	case *ConnectorToControl_ProxyResponseChunk:
		state, err := validator.proxyState(envelope, message.ProxyResponseChunk.GetRequestId().GetValue())
		if err != nil {
			return err
		}
		if !state.gotHeaders {
			return fmt.Errorf("proxy response chunk arrived before response headers")
		}
		if message.ProxyResponseChunk.GetSequence() != state.nextResponse {
			return fmt.Errorf("proxy response chunk sequence %d, want %d", message.ProxyResponseChunk.GetSequence(), state.nextResponse)
		}
		state.nextResponse++
	case *ConnectorToControl_ProxyEnd:
		requestID := message.ProxyEnd.GetRequestId().GetValue()
		state, err := validator.proxyState(envelope, requestID)
		if err != nil {
			return err
		}
		if message.ProxyEnd.GetReason() == ProxyEndReason_PROXY_END_REASON_COMPLETE && !state.gotHeaders {
			return fmt.Errorf("completed proxy response ended before response headers")
		}
		delete(validator.requests, requestID)
	}
	return nil
}

func (validator *StreamValidator) proxyState(envelope interface {
	GetDataPlaneId() *DataPlaneID
	GetConnectorInstanceId() *ConnectorInstanceID
}, requestID string) (*proxyRequestState, error) {
	state, exists := validator.requests[requestID]
	if !exists {
		return nil, fmt.Errorf("proxy request_id %q has not started", requestID)
	}
	if state.dataPlaneID != envelope.GetDataPlaneId().GetValue() || state.connectorID != envelope.GetConnectorInstanceId().GetValue() {
		return nil, fmt.Errorf("proxy request_id %q has a mismatched connector scope", requestID)
	}
	return state, nil
}
