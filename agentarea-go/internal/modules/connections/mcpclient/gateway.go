package mcpclient

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

// GatewayStartWait is how long a request waits out a cold start another
// request performs (the gateway's startup timeout).
const GatewayStartWait = 300 * time.Second

// GatewayRetry is GatewayStartRetryTransport: it repeats a request the
// gateway answered "workload is starting" (503 with X-AgentArea-MCP-Starting:
// 1, never forwarded, so a repeat cannot run a tool twice) for up to wait, and
// turns a classified startup failure into a *StartupFailureError.
func GatewayRetry(inner http.RoundTripper, wait time.Duration) http.RoundTripper {
	return &gatewayRetry{inner: inner, wait: wait, now: time.Now}
}

type gatewayRetry struct {
	inner http.RoundTripper
	wait  time.Duration
	now   func() time.Time
}

func (g *gatewayRetry) RoundTrip(req *http.Request) (*http.Response, error) {
	deadline := g.now().Add(g.wait)
	for {
		resp, err := g.inner.RoundTrip(req)
		if err != nil || resp.StatusCode != http.StatusServiceUnavailable {
			return resp, err
		}
		if d := strings.TrimSpace(resp.Header.Get(StartFailureHeader)); d != "" {
			_ = resp.Body.Close()
			return nil, &StartupFailureError{Detail: d}
		}
		if resp.Header.Get(StartingHeader) != "1" {
			return resp, nil
		}
		delay := time.Second
		if s, err := strconv.ParseFloat(resp.Header.Get("Retry-After"), 64); err == nil && s > 1 {
			delay = time.Duration(s * float64(time.Second))
		}
		if g.now().Add(delay).After(deadline) {
			return resp, nil
		}
		_ = resp.Body.Close()
		t := time.NewTimer(delay)
		select {
		case <-req.Context().Done():
			t.Stop()
			return nil, req.Context().Err()
		case <-t.C:
		}
		if req.GetBody != nil {
			body, err := req.GetBody()
			if err != nil {
				return nil, err
			}
			req = req.Clone(req.Context())
			req.Body = body
		}
	}
}

// HandlerTransport serves requests with h in process, as if over HTTP: the
// response body streams through a pipe while h writes it, and closing the
// body cancels the handler's request.
func HandlerTransport(h http.Handler) http.RoundTripper { return handlerTransport{h: h} }

type handlerTransport struct{ h http.Handler }

func (t handlerTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	ctx, cancel := context.WithCancel(req.Context())
	in := req.Clone(ctx)
	if in.Body == nil {
		in.Body = http.NoBody
	}
	in.RequestURI = req.URL.RequestURI()
	in.RemoteAddr = "127.0.0.1:0"
	if in.Host == "" {
		in.Host = req.URL.Host
	}
	if in.Proto == "" {
		in.Proto, in.ProtoMajor, in.ProtoMinor = "HTTP/1.1", 1, 1
	}
	pr, pw := io.Pipe()
	w := &pipeWriter{header: http.Header{}, pw: pw, ready: make(chan *http.Response, 1), req: req}
	go func() {
		defer func() {
			if p := recover(); p != nil {
				w.commit(http.StatusInternalServerError)
				pw.CloseWithError(fmt.Errorf("in-process handler panicked: %v", p))
				return
			}
			w.commit(http.StatusOK)
			_ = pw.Close()
		}()
		t.h.ServeHTTP(w, in)
	}()
	select {
	case resp := <-w.ready:
		resp.Body = &pipeBody{pr: pr, cancel: cancel}
		return resp, nil
	case <-req.Context().Done():
		cancel()
		pr.CloseWithError(req.Context().Err())
		return nil, req.Context().Err()
	}
}

type pipeWriter struct {
	header http.Header
	pw     *io.PipeWriter
	ready  chan *http.Response
	req    *http.Request
	once   sync.Once
}

func (w *pipeWriter) Header() http.Header { return w.header }

func (w *pipeWriter) commit(status int) {
	w.once.Do(func() {
		w.ready <- &http.Response{
			Status: fmt.Sprintf("%d %s", status, http.StatusText(status)), StatusCode: status,
			Proto: "HTTP/1.1", ProtoMajor: 1, ProtoMinor: 1,
			Header: w.header.Clone(), ContentLength: -1, Request: w.req,
		}
	})
}

func (w *pipeWriter) WriteHeader(status int) {
	if status < 200 {
		return
	}
	w.commit(status)
}

func (w *pipeWriter) Write(b []byte) (int, error) {
	w.commit(http.StatusOK)
	return w.pw.Write(b)
}

func (w *pipeWriter) Flush() { w.commit(http.StatusOK) }

type pipeBody struct {
	pr     *io.PipeReader
	cancel context.CancelFunc
}

func (b *pipeBody) Read(p []byte) (int, error) { return b.pr.Read(p) }

func (b *pipeBody) Close() error {
	b.cancel()
	return b.pr.Close()
}
