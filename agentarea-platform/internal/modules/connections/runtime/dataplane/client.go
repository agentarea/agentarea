// Package dataplane runs MCP workloads on a remote host: Client is the control
// plane's workload.Backend over HTTP, Host is the narrow authenticated API that
// host serves over its local backend. The host holds no database, secrets or
// event bus; it receives a fully resolved workload.Spec.
package dataplane

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

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

const (
	apiPrefix       = "/dataplane/v1"
	instancesPrefix = apiPrefix + "/instances/"
	minTokenLength  = 32
	clientTimeout   = 60 * time.Second
	maxResponse     = 4 << 20
)

// ClientConfig is how the control plane reaches a data plane.
type ClientConfig struct {
	BaseURL string
	Token   string
	Timeout time.Duration
}

// LoadClientConfig reads AGENTAREA_MCP_DATAPLANE_URL and
// AGENTAREA_MCP_DATAPLANE_TOKEN. The URL must be https unless
// AGENTAREA_MCP_DATAPLANE_INSECURE=true declares the hop private.
func LoadClientConfig(l *config.Loader) ClientConfig {
	base := strings.TrimSpace(l.RequiredEnv("AGENTAREA_MCP_DATAPLANE_URL"))
	token := l.RequiredEnv("AGENTAREA_MCP_DATAPLANE_TOKEN")
	insecure := l.BoolEnv("AGENTAREA_MCP_DATAPLANE_INSECURE", false)
	if token != "" && len(token) < minTokenLength {
		l.Fail("AGENTAREA_MCP_DATAPLANE_TOKEN", fmt.Errorf("must be at least %d characters, got %d", minTokenLength, len(token)))
	}
	if base != "" {
		parsed, err := url.Parse(base)
		switch {
		case err != nil || parsed.Scheme == "" || parsed.Host == "":
			l.Fail("AGENTAREA_MCP_DATAPLANE_URL", fmt.Errorf("must be an absolute URL, got %q", base))
		case parsed.Scheme != "https" && !insecure:
			l.Fail("AGENTAREA_MCP_DATAPLANE_URL", fmt.Errorf("is %s; the data-plane token would cross the network in cleartext. Use https, or set AGENTAREA_MCP_DATAPLANE_INSECURE=true when the hop is already private", parsed.Scheme))
		}
	}
	return ClientConfig{BaseURL: strings.TrimRight(base, "/"), Token: token, Timeout: clientTimeout}
}

// Client is a workload.Backend whose workloads run on a remote data plane.
type Client struct {
	base  *url.URL
	token string
	http  *http.Client
}

// NewClient talks to the data plane through transport, which the caller
// chooses (the internal netguard transport in the app).
func NewClient(cfg ClientConfig, transport http.RoundTripper) (*Client, error) {
	base, err := url.Parse(strings.TrimRight(cfg.BaseURL, "/"))
	if err != nil || base.Scheme == "" || base.Host == "" {
		return nil, fmt.Errorf("data-plane URL %q is not an absolute URL", cfg.BaseURL)
	}
	if len(cfg.Token) < minTokenLength {
		return nil, fmt.Errorf("data-plane token must be at least %d characters", minTokenLength)
	}
	if transport == nil {
		return nil, errors.New("data-plane client needs a transport")
	}
	timeout := cfg.Timeout
	if timeout <= 0 {
		timeout = clientTimeout
	}
	return &Client{base: base, token: cfg.Token, http: &http.Client{Transport: transport, Timeout: timeout}}, nil
}

// InstanceProxyURL is the data plane's authenticated entry point for one
// instance's MCP endpoint.
func (c *Client) InstanceProxyURL(instanceID string) string {
	return c.base.String() + instancesPrefix + url.PathEscape(instanceID) + "/proxy/mcp"
}

// Authorize attaches the machine credential to a request bound for this data
// plane's instance routes, and to nothing else: scheme, host and path prefix
// must all match. It reports whether it did.
func (c *Client) Authorize(r *http.Request) bool {
	if !c.IsInstanceURL(r.URL) {
		return false
	}
	r.Header.Set("Authorization", "Bearer "+c.token)
	return true
}

// IsInstanceURL reports whether u addresses this data plane's instance routes.
func (c *Client) IsInstanceURL(u *url.URL) bool {
	if u == nil || u.Scheme != c.base.Scheme || u.Host != c.base.Host {
		return false
	}
	return strings.HasPrefix(u.Path, strings.TrimRight(c.base.Path, "/")+instancesPrefix)
}

// ResponseError is a non-2xx answer of the data plane, with its status kept.
type ResponseError struct {
	Status int
	Method string
	Path   string
	Body   string
}

func (e *ResponseError) Error() string {
	return fmt.Sprintf("data plane %s %s returned %d: %s", e.Method, e.Path, e.Status, e.Body)
}

func statusOf(err error) int {
	var re *ResponseError
	if errors.As(err, &re) {
		return re.Status
	}
	return 0
}

func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("encoding data-plane request: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base.String()+path, reader)
	if err != nil {
		return fmt.Errorf("building data-plane request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("calling data plane %s %s: %w", method, path, err)
	}
	defer func() { _ = resp.Body.Close() }()
	payload, err := io.ReadAll(io.LimitReader(resp.Body, maxResponse))
	if err != nil {
		return fmt.Errorf("reading data-plane response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return &ResponseError{Status: resp.StatusCode, Method: method, Path: path, Body: strings.TrimSpace(string(payload))}
	}
	if out == nil || len(payload) == 0 {
		return nil
	}
	if err := json.Unmarshal(payload, out); err != nil {
		return fmt.Errorf("decoding data-plane response: %w", err)
	}
	return nil
}

func instancePath(id string) string { return instancesPrefix + url.PathEscape(id) }

// Create asks the data plane to start the workload.
func (c *Client) Create(ctx context.Context, spec workload.Spec) (workload.Status, error) {
	var st workload.Status
	if err := c.do(ctx, http.MethodPost, apiPrefix+"/instances", spec, &st); err != nil {
		return workload.Status{}, err
	}
	return st, nil
}

// Delete treats an unknown instance as retired: the control plane's records
// can outlive the workload.
func (c *Client) Delete(ctx context.Context, instanceID string) error {
	err := c.do(ctx, http.MethodDelete, instancePath(instanceID), nil, nil)
	if statusOf(err) == http.StatusNotFound {
		return nil
	}
	return err
}

// Status reports a missing instance as workload.ErrNotFound; any other
// failure stays an error so an outage is never read as absence.
func (c *Client) Status(ctx context.Context, instanceID string) (workload.Status, error) {
	var st workload.Status
	if err := c.do(ctx, http.MethodGet, instancePath(instanceID), nil, &st); err != nil {
		if statusOf(err) == http.StatusNotFound {
			return workload.Status{}, workload.ErrNotFound
		}
		return workload.Status{}, err
	}
	return st, nil
}

// Reservation asks the data plane, whose configuration sizes a new workload.
func (c *Client) Reservation(ctx context.Context) (workload.Reservation, error) {
	var r workload.Reservation
	if err := c.do(ctx, http.MethodGet, apiPrefix+"/reservation", nil, &r); err != nil {
		return workload.Reservation{}, err
	}
	return r, nil
}

// Ping proves the data plane is reachable and accepts the token.
func (c *Client) Ping(ctx context.Context) error {
	if _, err := c.Reservation(ctx); err != nil {
		return fmt.Errorf("data plane at %s is not usable: %w", c.base.Redacted(), err)
	}
	return nil
}
