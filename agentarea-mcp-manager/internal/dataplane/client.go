package dataplane

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
)

// Client is the control-plane half of data-plane mode: a backends.Backend that runs
// containers on a remote agent instead of on this host.
//
// It exists so the control plane can keep its database, secrets and policy on
// its own node while untrusted MCP containers run somewhere disposable. The
// Backend interface is already the seam both backends implement, so nothing
// above this layer has to know which one it got.
type Client struct {
	baseURL string
	token   string
	http    *http.Client
}

// ClientConfig is what the control plane needs to reach a data plane.
type ClientConfig struct {
	BaseURL string
	Token   string
	Timeout time.Duration
}

// ClientConfigFromEnv reads the remote data plane's address and credential.
//
// Both are required together. A URL without a token would talk to a data plane that
// must reject it, and a token without a URL names no data plane at all; neither is a
// state worth starting in.
func ClientConfigFromEnv() (*ClientConfig, error) {
	base := strings.TrimSpace(os.Getenv("MCP_DATAPLANE_URL"))
	token := os.Getenv("MCP_DATAPLANE_AUTH_TOKEN")

	if base == "" {
		return nil, fmt.Errorf("MCP_DATAPLANE_URL is required when BACKEND_TYPE=dataplane")
	}
	if token == "" {
		return nil, fmt.Errorf("MCP_DATAPLANE_AUTH_TOKEN is required when BACKEND_TYPE=dataplane")
	}
	parsed, err := url.Parse(base)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("MCP_DATAPLANE_URL must be an absolute URL, got %q", base)
	}
	if parsed.Scheme != "https" && os.Getenv("MCP_DATAPLANE_ALLOW_INSECURE") != "true" {
		return nil, fmt.Errorf(
			"MCP_DATAPLANE_URL is %s; the data-plane token would cross the network in cleartext. "+
				"Use https, or set MCP_DATAPLANE_ALLOW_INSECURE=true when the hop is already private (SSH tunnel, WireGuard)",
			parsed.Scheme,
		)
	}

	return &ClientConfig{BaseURL: strings.TrimRight(base, "/"), Token: token, Timeout: 60 * time.Second}, nil
}

func NewClient(cfg *ClientConfig) *Client {
	timeout := cfg.Timeout
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	return &Client{
		baseURL: strings.TrimRight(cfg.BaseURL, "/"),
		token:   cfg.Token,
		http:    &http.Client{Timeout: timeout},
	}
}

func (c *Client) do(ctx context.Context, method, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("encoding data-plane request: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
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
	defer resp.Body.Close()

	payload, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return fmt.Errorf("reading data-plane response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("data plane %s %s returned %d: %s", method, path, resp.StatusCode, strings.TrimSpace(string(payload)))
	}
	if out == nil || len(payload) == 0 {
		return nil
	}
	if err := json.Unmarshal(payload, out); err != nil {
		return fmt.Errorf("decoding data-plane response: %w", err)
	}
	return nil
}

func (c *Client) CreateInstance(ctx context.Context, spec *backends.InstanceSpec) (*backends.InstanceResult, error) {
	var result backends.InstanceResult
	if err := c.do(ctx, http.MethodPost, "/dataplane/v1/instances", spec, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

func (c *Client) DeleteInstance(ctx context.Context, instanceID string) error {
	return c.do(ctx, http.MethodDelete, "/dataplane/v1/instances/"+url.PathEscape(instanceID), nil, nil)
}

func (c *Client) GetInstanceStatus(ctx context.Context, instanceID string) (*backends.InstanceStatus, error) {
	var status backends.InstanceStatus
	if err := c.do(ctx, http.MethodGet, "/dataplane/v1/instances/"+url.PathEscape(instanceID), nil, &status); err != nil {
		return nil, err
	}
	return &status, nil
}

func (c *Client) ListInstances(ctx context.Context) ([]*backends.InstanceStatus, error) {
	var payload struct {
		Instances []*backends.InstanceStatus `json:"instances"`
	}
	if err := c.do(ctx, http.MethodGet, "/dataplane/v1/instances", nil, &payload); err != nil {
		return nil, err
	}
	return payload.Instances, nil
}

// UpdateInstance is not offered by the data-plane API.
//
// Reported rather than silently ignored: a caller that believes it changed an
// instance's image or environment and got no error would keep routing traffic
// to the old container.
func (c *Client) UpdateInstance(ctx context.Context, instanceID string, spec *backends.InstanceSpec) error {
	return fmt.Errorf("data-plane backend does not support in-place update of %s; delete and recreate the instance", instanceID)
}

func (c *Client) PerformHealthCheck(ctx context.Context, instanceID string) (*backends.HealthCheckResult, error) {
	var result backends.HealthCheckResult
	if err := c.do(ctx, http.MethodGet, "/dataplane/v1/instances/"+url.PathEscape(instanceID)+"/health", nil, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// Initialize proves the data plane is reachable and the token is accepted before the
// control plane reports itself ready. Discovering a bad token on the first user
// request instead would surface as a failed tool call.
func (c *Client) Initialize(ctx context.Context) error {
	probe, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()

	if err := c.do(probe, http.MethodGet, "/dataplane/v1/instances", nil, nil); err != nil {
		return fmt.Errorf("data plane at %s is not usable: %w", c.baseURL, err)
	}
	return nil
}

func (c *Client) Shutdown(ctx context.Context) error {
	c.http.CloseIdleConnections()
	return nil
}
