// Package connectorauth validates an incoming connector against the platform's
// public data-plane heartbeat endpoint. It deliberately has no database
// dependency: the platform remains the sole authority for node credentials.
package connectorauth

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

	"github.com/google/uuid"
)

const (
	defaultTimeout          = 10 * time.Second
	defaultMaxResponseBytes = int64(1 << 20)
	maxTimeout              = 60 * time.Second
	maxResponseBytes        = int64(4 << 20)
)

var (
	// ErrAuthenticationFailed intentionally does not distinguish invalid,
	// missing, revoked, or mismatched credentials.
	ErrAuthenticationFailed = errors.New("connector authentication failed")
	// ErrPlatformUnavailable identifies a platform call that could not finish
	// without exposing transport internals or request credentials.
	ErrPlatformUnavailable = errors.New("connector authentication unavailable")
)

// Config defines the platform endpoint used to authenticate connectors.
// PlatformAPIURL is the platform root URL, without /v1.
type Config struct {
	PlatformAPIURL           string
	AllowInsecureDevelopment bool
	Timeout                  time.Duration
	MaxResponseBytes         int64
}

func (c Config) normalized() (Config, *url.URL, error) {
	c.PlatformAPIURL = strings.TrimSpace(c.PlatformAPIURL)
	if c.Timeout == 0 {
		c.Timeout = defaultTimeout
	}
	if c.MaxResponseBytes == 0 {
		c.MaxResponseBytes = defaultMaxResponseBytes
	}
	if c.PlatformAPIURL == "" {
		return Config{}, nil, errors.New("platform API URL is required")
	}
	u, err := url.Parse(c.PlatformAPIURL)
	if err != nil || u.Scheme == "" || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return Config{}, nil, errors.New("platform API URL must be an absolute root URL without credentials, query, or fragment")
	}
	if u.Path != "" && u.Path != "/" {
		return Config{}, nil, errors.New("platform API URL must not include a path")
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && c.AllowInsecureDevelopment) {
		return Config{}, nil, errors.New("platform API URL must use HTTPS (set AllowInsecureDevelopment only for development)")
	}
	if c.Timeout <= 0 || c.Timeout > maxTimeout {
		return Config{}, nil, fmt.Errorf("platform API timeout must be between 1ns and %s", maxTimeout)
	}
	if c.MaxResponseBytes <= 0 || c.MaxResponseBytes > maxResponseBytes {
		return Config{}, nil, fmt.Errorf("maximum platform API response size must be between 1 and %d bytes", maxResponseBytes)
	}
	u.Path = ""
	u.RawPath = ""
	return c, u, nil
}

// Hello contains the connector metadata accepted during connection setup.
// NodeCredential intentionally lives outside this type so it cannot become a
// field of the heartbeat JSON by accident.
type Hello struct {
	ProtocolVersion     string
	DataPlaneID         string
	ConnectorInstanceID string
	Capabilities        map[string]bool
	AgentVersion        string
}

// IncomingConnector is supplied by the future Connect handler. The node
// credential is used only to construct the outbound Authorization header.
type IncomingConnector struct {
	Hello          Hello
	NodeCredential string
}

// AuthenticatedLogicalPlane is the non-secret identity the Connect handler
// may retain after platform authentication succeeds.
type AuthenticatedLogicalPlane struct {
	DataPlaneID         string
	ConnectorInstanceID string
	ProtocolVersion     string
	Capabilities        map[string]bool
	AgentVersion        string
	State               string
}

// Authenticator is the injectable boundary used by a connector Connect
// handler. It is intentionally independent of storage and HTTP transports.
type Authenticator interface {
	Authenticate(context.Context, IncomingConnector) (AuthenticatedLogicalPlane, error)
}

// Client authenticates connectors through the platform heartbeat API.
type Client struct {
	baseURL          *url.URL
	http             *http.Client
	maxResponseBytes int64
}

// NewClient constructs an authenticator. An optional HTTP client can supply a
// trusted TLS transport for private platform CAs; the configured timeout is
// always imposed on its copy.
func NewClient(config Config, client *http.Client) (*Client, error) {
	config, baseURL, err := config.normalized()
	if err != nil {
		return nil, err
	}
	if client == nil {
		client = &http.Client{}
	}
	copyClient := *client
	copyClient.Timeout = config.Timeout
	return &Client{baseURL: baseURL, http: &copyClient, maxResponseBytes: config.MaxResponseBytes}, nil
}

// Authenticate sends a ready heartbeat to the platform. The platform's 204
// response is the only successful authentication outcome.
func (c *Client) Authenticate(ctx context.Context, incoming IncomingConnector) (AuthenticatedLogicalPlane, error) {
	if err := validateIncoming(incoming); err != nil {
		return AuthenticatedLogicalPlane{}, ErrAuthenticationFailed
	}

	body, err := json.Marshal(heartbeatRequest{
		ProtocolVersion:     incoming.Hello.ProtocolVersion,
		DataPlaneID:         incoming.Hello.DataPlaneID,
		ConnectorInstanceID: incoming.Hello.ConnectorInstanceID,
		Capabilities:        incoming.Hello.Capabilities,
		AgentVersion:        incoming.Hello.AgentVersion,
		State:               "ready",
	})
	if err != nil {
		return AuthenticatedLogicalPlane{}, ErrAuthenticationFailed
	}

	endpoint := *c.baseURL
	endpoint.Path = "/v1/data-planes/" + url.PathEscape(incoming.Hello.DataPlaneID) + "/heartbeat"
	endpoint.RawPath = ""
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return AuthenticatedLogicalPlane{}, ErrPlatformUnavailable
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+incoming.NodeCredential)

	resp, err := c.http.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return AuthenticatedLogicalPlane{}, errors.Join(ErrPlatformUnavailable, ctx.Err())
		}
		return AuthenticatedLogicalPlane{}, ErrPlatformUnavailable
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		// Never decode or report an error body. A bounded discard permits safe
		// connection reuse without allowing a peer to consume unbounded memory.
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, c.maxResponseBytes))
		return AuthenticatedLogicalPlane{}, ErrAuthenticationFailed
	}

	return AuthenticatedLogicalPlane{
		DataPlaneID:         incoming.Hello.DataPlaneID,
		ConnectorInstanceID: incoming.Hello.ConnectorInstanceID,
		ProtocolVersion:     incoming.Hello.ProtocolVersion,
		Capabilities:        cloneCapabilities(incoming.Hello.Capabilities),
		AgentVersion:        incoming.Hello.AgentVersion,
		State:               "ready",
	}, nil
}

type heartbeatRequest struct {
	ProtocolVersion     string          `json:"protocol_version"`
	DataPlaneID         string          `json:"data_plane_id"`
	ConnectorInstanceID string          `json:"connector_instance_id"`
	Capabilities        map[string]bool `json:"capabilities"`
	AgentVersion        string          `json:"agent_version"`
	State               string          `json:"state"`
}

func validateIncoming(incoming IncomingConnector) error {
	if strings.TrimSpace(incoming.NodeCredential) == "" || strings.ContainsAny(incoming.NodeCredential, "\r\n") {
		return errors.New("invalid credential")
	}
	if _, err := uuid.Parse(incoming.Hello.DataPlaneID); err != nil {
		return errors.New("invalid data plane ID")
	}
	if strings.TrimSpace(incoming.Hello.ProtocolVersion) == "" || strings.TrimSpace(incoming.Hello.ConnectorInstanceID) == "" || strings.TrimSpace(incoming.Hello.AgentVersion) == "" {
		return errors.New("incomplete hello")
	}
	return nil
}

func cloneCapabilities(capabilities map[string]bool) map[string]bool {
	if capabilities == nil {
		return nil
	}
	clone := make(map[string]bool, len(capabilities))
	for capability, enabled := range capabilities {
		clone[capability] = enabled
	}
	return clone
}
