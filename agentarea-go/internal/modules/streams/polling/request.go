package polling

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

const (
	// Long enough for a long poll that waits at the provider.
	callTimeout = 90 * time.Second
	// What one answer may weigh; a bigger one is refused, not cut.
	maxResponseBytes = 32 << 20
)

// Caller sends a templated request: to a host the entry names as a vendor call, to a host
// the member names through the member transport, which vets and pins every hop.
type Caller struct {
	vendor *http.Client
	member *http.Client
}

// NewCaller builds both clients over the deployment's outbound clients.
func NewCaller(out netguard.Clients) *Caller {
	return &Caller{
		vendor: &http.Client{Transport: out.Transport(netguard.Vendor), Timeout: callTimeout},
		member: &http.Client{Transport: out.Transport(netguard.Member), Timeout: callTimeout},
	}
}

// MemberHost reports whether the host of a URL template comes from the member (holds a
// placeholder) rather than from the entry.
func MemberHost(urlTemplate string) bool {
	rest := urlTemplate
	if i := strings.Index(rest, "://"); i >= 0 {
		rest = rest[i+3:]
	}
	if i := strings.IndexAny(rest, "/?#"); i >= 0 {
		rest = rest[:i]
	}
	return rest == "" || strings.Contains(rest, "{")
}

// Call renders req with v, sends it and returns the body of a 2xx answer. Errors name the
// host only: a URL can carry a credential (a bot token in the path).
func (c *Caller) Call(ctx context.Context, req Request, v Values) ([]byte, error) {
	method := strings.ToUpper(req.Method)
	if method == "" {
		method = http.MethodGet
	}
	rawURL, err := Render(req.URL, v)
	if err != nil {
		return nil, fmt.Errorf("request url: %w", err)
	}
	target, err := url.Parse(rawURL)
	if err != nil || target.Host == "" || (target.Scheme != "https" && target.Scheme != "http") {
		return nil, errors.New("request url is not an http(s) URL")
	}
	host := target.Scheme + "://" + target.Host
	var body io.Reader
	if req.JSON != nil {
		rendered, err := RenderJSON(req.JSON, v)
		if err != nil {
			return nil, fmt.Errorf("request body: %w", err)
		}
		encoded, err := json.Marshal(rendered)
		if err != nil {
			return nil, fmt.Errorf("request body: %w", err)
		}
		body = bytes.NewReader(encoded)
	}
	httpReq, err := http.NewRequestWithContext(ctx, method, target.String(), body)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, host, err)
	}
	if body != nil {
		httpReq.Header.Set("Content-Type", "application/json")
	}
	for name, tmpl := range req.Headers {
		value, err := Render(tmpl, v)
		if err != nil {
			return nil, fmt.Errorf("request header %s: %w", name, err)
		}
		httpReq.Header.Set(name, value)
	}
	client := c.vendor
	if MemberHost(req.URL) {
		client = c.member
	}
	resp, err := client.Do(httpReq)
	if err != nil {
		var urlErr *url.Error
		if errors.As(err, &urlErr) {
			err = urlErr.Err
		}
		return nil, fmt.Errorf("%s %s: %w", method, host, err)
	}
	defer func() { _ = resp.Body.Close() }()
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil {
		return nil, fmt.Errorf("%s %s: read answer: %w", method, host, err)
	}
	if len(data) > maxResponseBytes {
		return nil, fmt.Errorf("%s %s: answer is over %d bytes", method, host, maxResponseBytes)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return nil, fmt.Errorf("%s %s: HTTP %d: %s", method, host, resp.StatusCode, excerpt(data))
	}
	return data, nil
}

func excerpt(data []byte) string {
	const limit = 300
	text := strings.TrimSpace(string(data))
	if len(text) > limit {
		return text[:limit] + "..."
	}
	return text
}
