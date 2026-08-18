package connectorbackend

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/connectorhub"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
)

const defaultRequestChunkBytes = 32 << 10

// ProxyHub is the connectorhub surface needed by HTTP proxying.
type ProxyHub interface {
	OpenProxy(context.Context, string, connectorhub.ProxyRequest) (*connectorhub.ProxyCall, error)
}

// RoundTripper forwards an HTTP request through one pinned connector. It is a
// normal http.RoundTripper so mcpgateway can use it without an address for the
// selected data plane.
type RoundTripper struct {
	hub         ProxyHub
	dataPlaneID string
	chunkBytes  int
}

var _ http.RoundTripper = (*RoundTripper)(nil)

func NewRoundTripper(hub ProxyHub, dataPlaneID string, requestChunkBytes ...int) (*RoundTripper, error) {
	if hub == nil {
		return nil, fmt.Errorf("connector hub is required")
	}
	if strings.TrimSpace(dataPlaneID) == "" {
		return nil, fmt.Errorf("data_plane_id is required")
	}
	chunkBytes := defaultRequestChunkBytes
	if len(requestChunkBytes) > 1 {
		return nil, fmt.Errorf("at most one request chunk size is allowed")
	}
	if len(requestChunkBytes) == 1 {
		chunkBytes = requestChunkBytes[0]
	}
	if chunkBytes <= 0 || chunkBytes > connectorproto.MaxChunkBytes {
		return nil, fmt.Errorf("request chunk size must be between 1 and %d", connectorproto.MaxChunkBytes)
	}
	return &RoundTripper{hub: hub, dataPlaneID: dataPlaneID, chunkBytes: chunkBytes}, nil
}

// RoundTrip starts request-body delivery before waiting for response headers.
// That ordering permits MCP streaming endpoints to send their first response
// chunk before the request body reaches EOF.
func (t *RoundTripper) RoundTrip(request *http.Request) (*http.Response, error) {
	if request == nil || request.URL == nil {
		return nil, fmt.Errorf("HTTP request and URL are required")
	}
	if request.Method == "" {
		return nil, fmt.Errorf("HTTP method is required")
	}
	path := request.URL.EscapedPath()
	if path == "" {
		path = "/"
	}
	if request.URL.RawQuery != "" {
		path += "?" + request.URL.RawQuery
	}
	call, err := t.hub.OpenProxy(request.Context(), t.dataPlaneID, connectorhub.ProxyRequest{
		Method:   request.Method,
		Path:     path,
		Headers:  requestHeaders(request.Header),
		Deadline: requestDeadline(request.Context()),
	})
	if err != nil {
		return nil, err
	}

	writeErr := make(chan error, 1)
	writerDone := make(chan struct{})
	go func() {
		defer close(writerDone)
		writeErr <- writeRequest(request.Context(), call, request.Body, t.chunkBytes)
	}()
	// A connector can respond before a request body is drained. If the HTTP
	// caller disappears at that point, closing the source body unblocks the
	// writer as well as closing the hub proxy exchange.
	if request.Body != nil {
		go func() {
			select {
			case <-request.Context().Done():
				_ = request.Body.Close()
			case <-writerDone:
			}
		}()
	}

	headers, err := call.Headers(request.Context())
	if err != nil {
		call.Close()
		return nil, err
	}
	responseHeaders := make(http.Header)
	for _, h := range filteredHeaders(headers.Headers) {
		responseHeaders.Add(h.Name, h.Value)
	}
	return &http.Response{
		StatusCode: headers.StatusCode,
		Status:     fmt.Sprintf("%d %s", headers.StatusCode, http.StatusText(headers.StatusCode)),
		Header:     responseHeaders,
		Body:       &proxyBody{call: call, ctx: request.Context(), writeErr: writeErr, requestBody: request.Body},
		Request:    request,
	}, nil
}

func requestDeadline(ctx context.Context) time.Time {
	deadline, _ := ctx.Deadline()
	return deadline
}

func writeRequest(ctx context.Context, call *connectorhub.ProxyCall, body io.ReadCloser, chunkBytes int) error {
	if body != nil {
		defer body.Close()
		buf := make([]byte, chunkBytes)
		for {
			n, err := body.Read(buf)
			if n > 0 {
				if writeErr := call.Write(ctx, buf[:n]); writeErr != nil {
					call.Close()
					return writeErr
				}
			}
			if errors.Is(err, io.EOF) {
				break
			}
			if err != nil {
				call.Close()
				return err
			}
		}
	}
	if err := call.CloseRequest(ctx); err != nil {
		call.Close()
		return err
	}
	return nil
}

type proxyBody struct {
	call        *connectorhub.ProxyCall
	ctx         context.Context
	writeErr    <-chan error
	requestBody io.Closer

	mu      sync.Mutex
	current []byte
	closed  bool
}

func (b *proxyBody) Read(dst []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for len(b.current) == 0 {
		if b.closed {
			return 0, io.ErrClosedPipe
		}
		chunk, err := b.call.Read(b.ctx)
		if err != nil {
			select {
			case writeErr := <-b.writeErr:
				if writeErr != nil {
					return 0, writeErr
				}
			default:
			}
			return 0, err
		}
		b.current = chunk
	}
	n := copy(dst, b.current)
	b.current = b.current[n:]
	return n, nil
}

func (b *proxyBody) Close() error {
	b.mu.Lock()
	if !b.closed {
		b.closed = true
		b.current = nil
		if b.requestBody != nil {
			_ = b.requestBody.Close()
		}
		b.call.Close()
	}
	b.mu.Unlock()
	return nil
}

func requestHeaders(headers http.Header) []connectorhub.Header {
	return filteredHeaders(flattenHeaders(headers))
}

func flattenHeaders(headers http.Header) []connectorhub.Header {
	result := make([]connectorhub.Header, 0, len(headers))
	for name, values := range headers {
		for _, value := range values {
			result = append(result, connectorhub.Header{Name: name, Value: value})
		}
	}
	return result
}

func filteredHeaders(headers []connectorhub.Header) []connectorhub.Header {
	connectionTokens := make(map[string]struct{})
	for _, h := range headers {
		if strings.EqualFold(h.Name, "Connection") {
			for _, token := range strings.Split(h.Value, ",") {
				connectionTokens[strings.ToLower(strings.TrimSpace(token))] = struct{}{}
			}
		}
	}
	result := make([]connectorhub.Header, 0, len(headers))
	for _, h := range headers {
		name := strings.ToLower(h.Name)
		if _, listed := connectionTokens[name]; listed || hopByHopHeader(name) {
			continue
		}
		result = append(result, h)
	}
	return result
}

func hopByHopHeader(name string) bool {
	switch strings.ToLower(name) {
	case "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade":
		return true
	default:
		return false
	}
}
