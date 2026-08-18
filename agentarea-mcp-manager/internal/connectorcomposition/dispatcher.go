package connectorcomposition

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/connectorruntime"
	"github.com/agentarea/mcp-manager/internal/connectorsandbox"
	"github.com/agentarea/mcp-manager/internal/connectortransport"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
)

const proxyInstanceHeader = "X-Agentarea-Instance-Id"

var _ connectortransport.Dispatcher = (*Dispatcher)(nil)

// Dispatcher translates the bounded connector wire contract into local MCP
// and sandbox adapters. Missing adapters are rejected per operation instead of
// being represented by an optimistic capability bit.
type Dispatcher struct{ runtime *Runtime }

func (r *Runtime) Dispatcher() *Dispatcher { return &Dispatcher{runtime: r} }

func (d *Dispatcher) DispatchOperation(ctx context.Context, start *connectorproto.OperationStart) (*connectorproto.OperationResult, error) {
	if start == nil || start.GetOperationId() == nil {
		return operationFailure(start, connectorproto.ErrorCode_ERROR_CODE_INVALID_ARGUMENT, "operation is required"), nil
	}
	var response any
	var err error
	switch start.GetKind() {
	case connectorproto.OperationKind_OPERATION_KIND_MCP_CREATE:
		var request backends.InstanceSpec
		err = decodeJSON(start.GetRequestPayload(), &request)
		if err == nil {
			if d.runtime == nil || d.runtime.mcp == nil {
				err = errUnavailable("MCP")
			} else {
				response, err = d.runtime.mcp.Create(ctx, &request)
			}
		}
	case connectorproto.OperationKind_OPERATION_KIND_MCP_DELETE:
		var request instanceRequest
		err = decodeJSON(start.GetRequestPayload(), &request)
		if err == nil {
			if d.runtime == nil || d.runtime.mcp == nil {
				err = errUnavailable("MCP")
			} else {
				response, err = d.runtime.mcp.Delete(ctx, request.InstanceID)
			}
		}
	case connectorproto.OperationKind_OPERATION_KIND_MCP_GET:
		var request instanceRequest
		err = decodeJSON(start.GetRequestPayload(), &request)
		if err == nil {
			if d.runtime == nil || d.runtime.mcp == nil {
				err = errUnavailable("MCP")
			} else {
				response, err = d.runtime.mcp.Get(ctx, request.InstanceID)
			}
		}
	case connectorproto.OperationKind_OPERATION_KIND_MCP_LIST:
		var request struct{}
		err = decodeJSON(start.GetRequestPayload(), &request)
		if err == nil {
			if d.runtime == nil || d.runtime.mcp == nil {
				err = errUnavailable("MCP")
			} else {
				response, err = d.runtime.mcp.List(ctx)
			}
		}
	case connectorproto.OperationKind_OPERATION_KIND_MCP_HEALTH:
		var request instanceRequest
		err = decodeJSON(start.GetRequestPayload(), &request)
		if err == nil {
			if d.runtime == nil || d.runtime.mcp == nil {
				err = errUnavailable("MCP")
			} else {
				response, err = d.runtime.mcp.Health(ctx, request.InstanceID)
			}
		}
	case connectorproto.OperationKind_OPERATION_KIND_SANDBOX_EXECUTE:
		response, err = d.sandboxExecute(ctx, start.GetRequestPayload())
	case connectorproto.OperationKind_OPERATION_KIND_SANDBOX_FILE_PUT:
		response, err = d.sandboxFilePut(ctx, start.GetRequestPayload())
	case connectorproto.OperationKind_OPERATION_KIND_SANDBOX_FILE_GET:
		response, err = d.sandboxFileGet(ctx, start.GetRequestPayload())
	case connectorproto.OperationKind_OPERATION_KIND_SANDBOX_FILE_LIST:
		response, err = d.sandboxFileList(ctx, start.GetRequestPayload())
	case connectorproto.OperationKind_OPERATION_KIND_SANDBOX_TASK_RETIRE:
		response, err = d.sandboxRetire(ctx, start.GetRequestPayload())
	case connectorproto.OperationKind_OPERATION_KIND_SANDBOX_WORKSPACE_ENSURE, connectorproto.OperationKind_OPERATION_KIND_SANDBOX_WORKSPACE_HYDRATE:
		err = fmt.Errorf("workspace import commands require an agent-local workspace source")
	default:
		err = fmt.Errorf("unsupported operation")
	}
	if err != nil {
		if d.runtime != nil && d.runtime.reportError != nil {
			d.runtime.reportError(err)
		}
		return operationFailure(start, errorCode(err), "operation failed"), nil
	}
	payload, err := json.Marshal(response)
	if err != nil || len(payload) > connectorproto.MaxOperationResponseBytes {
		return operationFailure(start, connectorproto.ErrorCode_ERROR_CODE_INTERNAL, "operation response is too large"), nil
	}
	return &connectorproto.OperationResult{OperationId: start.GetOperationId(), Status: connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_SUCCEEDED, ResponsePayload: payload, ContentType: "application/json"}, nil
}

type instanceRequest struct {
	InstanceID string `json:"instance_id"`
}

func (d *Dispatcher) sandbox() (*connectorsandbox.Dispatcher, error) {
	if d.runtime == nil || d.runtime.sandbox == nil {
		return nil, errUnavailable("sandbox")
	}
	return d.runtime.sandbox, nil
}

func (d *Dispatcher) sandboxExecute(ctx context.Context, payload []byte) (any, error) {
	var request struct {
		ExecutionID string                         `json:"execution_id"`
		Request     sandboxcontract.ExecuteRequest `json:"request"`
	}
	if err := decodeJSON(payload, &request); err != nil {
		return nil, err
	}
	dispatcher, err := d.sandbox()
	if err != nil {
		return nil, err
	}
	result, err := dispatcher.Dispatch(ctx, connectorsandbox.Command{Operation: connectorsandbox.OperationExecute, WorkspaceID: request.Request.WorkspaceID, TaskID: request.Request.TaskID, ExecutionID: request.ExecutionID, Execute: &request.Request})
	if err != nil {
		return nil, err
	}
	return result.Execute, nil
}

func (d *Dispatcher) sandboxFilePut(ctx context.Context, payload []byte) (any, error) {
	var request sandboxcontract.FilePutRequest
	if err := decodeJSON(payload, &request); err != nil {
		return nil, err
	}
	dispatcher, err := d.sandbox()
	if err != nil {
		return nil, err
	}
	result, err := dispatcher.Dispatch(ctx, connectorsandbox.Command{Operation: connectorsandbox.OperationFilePut, WorkspaceID: request.WorkspaceID, TaskID: request.TaskID, FilePut: &request})
	if err != nil {
		return nil, err
	}
	return result.FilePut, nil
}

func (d *Dispatcher) sandboxFileGet(ctx context.Context, payload []byte) (any, error) {
	var request struct {
		WorkspaceID string `json:"workspace_id"`
		TaskID      string `json:"task_id"`
		Path        string `json:"path"`
	}
	if err := decodeJSON(payload, &request); err != nil {
		return nil, err
	}
	dispatcher, err := d.sandbox()
	if err != nil {
		return nil, err
	}
	result, err := dispatcher.Dispatch(ctx, connectorsandbox.Command{Operation: connectorsandbox.OperationFileGet, WorkspaceID: request.WorkspaceID, TaskID: request.TaskID, Path: request.Path})
	if err != nil {
		return nil, err
	}
	return result.FileGet, nil
}

func (d *Dispatcher) sandboxFileList(ctx context.Context, payload []byte) (any, error) {
	var request struct {
		WorkspaceID string `json:"workspace_id"`
		TaskID      string `json:"task_id"`
		Prefix      string `json:"prefix"`
	}
	if err := decodeJSON(payload, &request); err != nil {
		return nil, err
	}
	dispatcher, err := d.sandbox()
	if err != nil {
		return nil, err
	}
	result, err := dispatcher.Dispatch(ctx, connectorsandbox.Command{Operation: connectorsandbox.OperationFileList, WorkspaceID: request.WorkspaceID, TaskID: request.TaskID, Prefix: request.Prefix})
	if err != nil {
		return nil, err
	}
	return result.FileList, nil
}

func (d *Dispatcher) sandboxRetire(ctx context.Context, payload []byte) (any, error) {
	var request struct {
		WorkspaceID string `json:"workspace_id"`
		TaskID      string `json:"task_id"`
		IdleTTL     string `json:"idle_ttl,omitempty"`
	}
	if err := decodeJSON(payload, &request); err != nil {
		return nil, err
	}
	idle := time.Duration(0)
	if request.IdleTTL != "" {
		var err error
		idle, err = time.ParseDuration(request.IdleTTL)
		if err != nil {
			return nil, err
		}
	}
	dispatcher, err := d.sandbox()
	if err != nil {
		return nil, err
	}
	_, err = dispatcher.Dispatch(ctx, connectorsandbox.Command{Operation: connectorsandbox.OperationTaskRetire, WorkspaceID: request.WorkspaceID, TaskID: request.TaskID, IdleTTL: idle})
	return struct{}{}, err
}

func (d *Dispatcher) StartProxy(ctx context.Context, start *connectorproto.ProxyStart) (connectortransport.ProxyExchange, error) {
	if d.runtime == nil || d.runtime.mcp == nil {
		return nil, errUnavailable("MCP")
	}
	if start == nil {
		return nil, errors.New("proxy start is required")
	}
	instanceID, headers := proxyTarget(start.GetHeaders())
	if instanceID == "" {
		return nil, fmt.Errorf("%s header is required", proxyInstanceHeader)
	}
	requestCtx, cancel := context.WithCancel(ctx)
	reader, writer := io.Pipe()
	exchange := &proxyExchange{writer: writer, cancel: cancel, responses: make(chan connectortransport.ProxyResponse, 1), done: make(chan struct{})}
	go func() {
		defer close(exchange.responses)
		defer reader.Close()
		defer cancel()
		err := d.runtime.mcp.ExecuteHTTPStream(requestCtx, connectorruntime.HTTPRequest{InstanceID: instanceID, Method: start.GetMethod(), Path: start.GetTargetPath(), Header: headers, Body: reader}, exchange)
		if err != nil {
			exchange.end(connectorproto.ProxyEndReason_PROXY_END_REASON_ERROR)
			return
		}
		exchange.end(connectorproto.ProxyEndReason_PROXY_END_REASON_COMPLETE)
	}()
	return exchange, nil
}

func proxyTarget(headers []*connectorproto.Header) (string, http.Header) {
	result := make(http.Header, len(headers))
	var instanceID string
	for _, header := range headers {
		if strings.EqualFold(header.GetName(), proxyInstanceHeader) {
			instanceID = header.GetValue()
			continue
		}
		result.Add(header.GetName(), header.GetValue())
	}
	return instanceID, result
}

type proxyExchange struct {
	writer    *io.PipeWriter
	cancel    context.CancelFunc
	responses chan connectortransport.ProxyResponse
	once      sync.Once
	closeOnce sync.Once
	done      chan struct{}
	sequence  uint64
}

func (p *proxyExchange) WriteProxyRequest(ctx context.Context, chunk *connectorproto.ProxyRequestChunk) error {
	if chunk == nil {
		return errors.New("proxy request chunk is required")
	}
	done := make(chan error, 1)
	go func() { _, err := p.writer.Write(chunk.GetData()); done <- err }()
	select {
	case <-p.done:
		return context.Canceled
	case <-ctx.Done():
		return ctx.Err()
	case err := <-done:
		return err
	}
}
func (p *proxyExchange) EndProxyRequest(_ context.Context, end *connectorproto.ProxyRequestEnd) error {
	if end == nil {
		return errors.New("proxy request end is required")
	}
	if end.GetReason() == connectorproto.ProxyEndReason_PROXY_END_REASON_COMPLETE {
		return p.writer.Close()
	}
	p.cancel()
	return p.writer.CloseWithError(errors.New("proxy request terminated"))
}
func (p *proxyExchange) Responses() <-chan connectortransport.ProxyResponse { return p.responses }
func (p *proxyExchange) Close() error {
	p.closeOnce.Do(func() {
		p.cancel()
		close(p.done)
	})
	return p.writer.Close()
}
func (p *proxyExchange) WriteHeaders(_ context.Context, headers connectorruntime.HTTPResponseHeaders) error {
	response := &connectorproto.ProxyResponseHeaders{StatusCode: uint32(headers.StatusCode)}
	for name, values := range headers.Header {
		for _, value := range values {
			response.Headers = append(response.Headers, &connectorproto.Header{Name: name, Value: value})
		}
	}
	select {
	case <-p.done:
		return context.Canceled
	case p.responses <- connectortransport.ProxyResponse{Headers: response}:
		return nil
	}
}
func (p *proxyExchange) WriteChunk(ctx context.Context, chunk []byte) error {
	copy := append([]byte(nil), chunk...)
	response := &connectorproto.ProxyResponseChunk{Sequence: p.sequence, Data: copy}
	p.sequence++
	select {
	case <-p.done:
		return context.Canceled
	case <-ctx.Done():
		return ctx.Err()
	case p.responses <- connectortransport.ProxyResponse{Chunk: response}:
		return nil
	}
}
func (p *proxyExchange) end(reason connectorproto.ProxyEndReason) {
	p.once.Do(func() {
		select {
		case <-p.done:
		case p.responses <- connectortransport.ProxyResponse{End: &connectorproto.ProxyEnd{Reason: reason}}:
		}
	})
}

func decodeJSON(payload []byte, value any) error {
	decoder := json.NewDecoder(strings.NewReader(string(payload)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return fmt.Errorf("invalid operation payload: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("invalid operation payload")
	}
	return nil
}
func errUnavailable(capability string) error {
	return fmt.Errorf("%s capability is not configured", capability)
}
func operationFailure(start *connectorproto.OperationStart, code connectorproto.ErrorCode, message string) *connectorproto.OperationResult {
	var id *connectorproto.OperationID
	if start != nil {
		id = start.GetOperationId()
	}
	return &connectorproto.OperationResult{OperationId: id, Status: connectorproto.OperationResultStatus_OPERATION_RESULT_STATUS_FAILED, Error: &connectorproto.Error{Code: code, Message: message}}
}
func errorCode(err error) connectorproto.ErrorCode {
	if errors.Is(err, connectorruntime.ErrNotFound) || errors.Is(err, backends.ErrInstanceNotFound) {
		return connectorproto.ErrorCode_ERROR_CODE_NOT_FOUND
	}
	if errors.Is(err, connectorruntime.ErrUnowned) {
		return connectorproto.ErrorCode_ERROR_CODE_PERMISSION_DENIED
	}
	if errors.Is(err, connectorsandbox.ErrCapabilityUnavailable) || strings.Contains(err.Error(), "not configured") {
		return connectorproto.ErrorCode_ERROR_CODE_UNAVAILABLE
	}
	if strings.Contains(err.Error(), "unsupported") {
		return connectorproto.ErrorCode_ERROR_CODE_UNSUPPORTED
	}
	if strings.Contains(err.Error(), "invalid") || strings.Contains(err.Error(), "required") {
		return connectorproto.ErrorCode_ERROR_CODE_INVALID_ARGUMENT
	}
	return connectorproto.ErrorCode_ERROR_CODE_INTERNAL
}
