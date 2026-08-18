package dataplaneconnect

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

type Identity struct {
	DataPlaneID         DataPlaneID         `json:"data_plane_id"`
	ConnectorInstanceID ConnectorInstanceID `json:"connector_instance_id"`
	NodeID              string              `json:"node_id,omitempty"`
	NodeCredential      string              `json:"node_credential"`
}

func ReadIdentity(path string) (Identity, error) {
	info, err := os.Stat(path)
	if err != nil {
		return Identity{}, fmt.Errorf("read identity: %w", err)
	}
	if info.Mode().Perm() != 0600 {
		return Identity{}, fmt.Errorf("identity file must have mode 0600")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return Identity{}, fmt.Errorf("read identity: %w", err)
	}
	var i Identity
	if err := json.Unmarshal(b, &i); err != nil {
		return Identity{}, fmt.Errorf("decode identity: %w", err)
	}
	if i.DataPlaneID == "" || i.ConnectorInstanceID == "" || i.NodeCredential == "" {
		return Identity{}, fmt.Errorf("identity is incomplete")
	}
	if _, err := uuid.Parse(string(i.DataPlaneID)); err != nil {
		return Identity{}, fmt.Errorf("identity data_plane_id must be a UUID")
	}
	return i, nil
}

func WriteIdentityAtomic(path string, identity Identity) error {
	b, err := json.Marshal(identity)
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return fmt.Errorf("create identity directory: %w", err)
	}
	if err := os.Chmod(dir, 0700); err != nil {
		return fmt.Errorf("secure identity directory: %w", err)
	}
	tmp, err := os.CreateTemp(dir, ".identity-")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if err := tmp.Chmod(0600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(b); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, path); err != nil {
		return err
	}
	parent, err := os.Open(dir)
	if err != nil {
		return fmt.Errorf("open identity directory: %w", err)
	}
	defer parent.Close()
	if err := parent.Sync(); err != nil {
		return fmt.Errorf("sync identity directory: %w", err)
	}
	return nil
}

type Client struct {
	cfg  Config
	http *http.Client

	mu               sync.RWMutex
	capabilitySource CapabilitySource
	connectorStream  ConnectorStream
}

// CapabilitySource exposes only initialized adapter facts. Configured
// capability booleans are intentionally never used for enrollment or
// heartbeats: an unconfigured provider must not be advertised.
type CapabilitySource interface {
	Capabilities() (mcp, sandbox bool)
}

// ConnectorStream is the narrow outbound transport seam. Its implementation
// owns ConnectRPC protocol details and never opens a listener.
type ConnectorStream interface {
	Run(context.Context) error
}

// DrainingConnectorStream optionally sends a protocol drain before shutdown.
// It is kept optional while control-plane transport rolls out independently.
type DrainingConnectorStream interface {
	ConnectorStream
	Drain(context.Context) error
}

const connectorShutdownTimeout = 5 * time.Second

func NewClient(cfg Config) (*Client, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &Client{
		cfg:  cfg,
		http: &http.Client{Timeout: cfg.HTTPTimeout},
	}, nil
}

func (c *Client) SetCapabilitySource(source CapabilitySource) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.capabilitySource = source
}

func (c *Client) SetConnectorStream(stream ConnectorStream) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.connectorStream = stream
}

func (c *Client) capabilities() Capabilities {
	c.mu.RLock()
	source := c.capabilitySource
	c.mu.RUnlock()
	if source == nil {
		return Capabilities{}
	}
	mcp, sandbox := source.Capabilities()
	return Capabilities{MCP: mcp, Sandbox: sandbox}
}

func (c *Client) stream() ConnectorStream {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.connectorStream
}

func (c *Client) Join(ctx context.Context) error {
	tokenBytes, err := os.ReadFile(c.cfg.EnrollmentTokenFile)
	if err != nil {
		return fmt.Errorf("read enrollment token: %w", err)
	}
	token := strings.TrimSpace(string(tokenBytes))
	if token == "" {
		return fmt.Errorf("enrollment token is empty")
	}
	connectorID := c.cfg.ConnectorInstanceID
	if connectorID == "" {
		if identity, readErr := ReadIdentity(c.cfg.IdentityFile); readErr == nil {
			if c.cfg.DataPlaneID != "" && identity.DataPlaneID != c.cfg.DataPlaneID {
				return fmt.Errorf("existing identity data_plane_id does not match configuration")
			}
			connectorID = identity.ConnectorInstanceID
		} else if !errors.Is(readErr, os.ErrNotExist) {
			return readErr
		}
	}
	if connectorID == "" {
		var err error
		connectorID, err = newConnectorInstanceID()
		if err != nil {
			return err
		}
	}

	var response EnrollmentResponse
	request := EnrollmentRequest{
		ProtocolVersion:     ProtocolVersion,
		DataPlaneID:         c.cfg.DataPlaneID,
		ConnectorInstanceID: connectorID,
		EnrollmentToken:     token,
		Capabilities:        c.capabilities(),
	}
	if err := c.request(ctx, http.MethodPost, EnrollmentExchangePath, request, "", &response); err != nil {
		return err
	}
	if response.DataPlaneID == "" || response.NodeCredential == "" {
		return fmt.Errorf("invalid enrollment response")
	}
	if _, err := uuid.Parse(string(response.DataPlaneID)); err != nil {
		return fmt.Errorf("invalid enrollment response")
	}
	if response.NodeID != "" {
		if _, err := uuid.Parse(response.NodeID); err != nil {
			return fmt.Errorf("invalid enrollment response")
		}
	}
	if c.cfg.DataPlaneID != "" && response.DataPlaneID != c.cfg.DataPlaneID {
		return fmt.Errorf("invalid enrollment response")
	}
	return WriteIdentityAtomic(c.cfg.IdentityFile, Identity{
		DataPlaneID:         response.DataPlaneID,
		ConnectorInstanceID: connectorID,
		NodeID:              response.NodeID,
		NodeCredential:      response.NodeCredential,
	})
}

func (c *Client) Heartbeat(ctx context.Context) error {
	i, err := ReadIdentity(c.cfg.IdentityFile)
	if err != nil {
		return err
	}
	path := fmt.Sprintf(HeartbeatPathFormat, url.PathEscape(string(i.DataPlaneID)))
	request := HeartbeatRequest{
		ProtocolVersion:     ProtocolVersion,
		DataPlaneID:         i.DataPlaneID,
		ConnectorInstanceID: i.ConnectorInstanceID,
		Capabilities:        c.capabilities(),
		AgentVersion:        c.cfg.AgentVersion,
	}
	return c.request(ctx, http.MethodPost, path, request, i.NodeCredential, nil)
}

func newConnectorInstanceID() (ConnectorInstanceID, error) {
	bytes := make([]byte, 16)
	if _, err := rand.Read(bytes); err != nil {
		return "", fmt.Errorf("generate connector instance ID: %w", err)
	}
	return ConnectorInstanceID(fmt.Sprintf("connector-%x", bytes)), nil
}

func (c *Client) Doctor(ctx context.Context) error {
	return c.Heartbeat(ctx)
}
func (c *Client) Run(ctx context.Context) error {
	if err := c.Heartbeat(ctx); err != nil {
		if heartbeatRejected(err) {
			return err
		}
	}
	stream := c.stream()
	if stream == nil {
		return c.runHeartbeats(ctx)
	}
	return c.runWithStream(ctx, stream)
}

func (c *Client) runHeartbeats(ctx context.Context) error {
	ticker := time.NewTicker(c.cfg.HeartbeatInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if err := c.Heartbeat(ctx); err != nil {
				if heartbeatRejected(err) {
					return err
				}
			}
		}
	}
}

func (c *Client) runWithStream(ctx context.Context, stream ConnectorStream) error {
	streamCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	streamResult := make(chan error, 1)
	go func() { streamResult <- stream.Run(streamCtx) }()

	ticker := time.NewTicker(c.cfg.HeartbeatInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			if draining, ok := stream.(DrainingConnectorStream); ok {
				drainCtx, drainCancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Second)
				_ = draining.Drain(drainCtx)
				drainCancel()
			}
			cancel()
			waitForConnectorStop(streamResult, connectorShutdownTimeout)
			return nil
		case err := <-streamResult:
			if err != nil && !errors.Is(err, context.Canceled) {
				return fmt.Errorf("connector stream: %w", err)
			}
			return nil
		case <-ticker.C:
			if err := c.Heartbeat(streamCtx); err != nil {
				if heartbeatRejected(err) {
					cancel()
					waitForConnectorStop(streamResult, connectorShutdownTimeout)
					return err
				}
			}
		}
	}
}

// A transport implementation must honor context cancellation, but shutdown
// cannot depend on that invariant: a wedged network stack or provider must not
// prevent a service manager from stopping and restarting the host agent.
func waitForConnectorStop(result <-chan error, timeout time.Duration) {
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case <-result:
	case <-timer.C:
	}
}

// ControlPlaneStatusError reports only the status class. Response bodies are
// intentionally discarded because they can contain implementation details or
// echoed credentials.
type ControlPlaneStatusError struct{ StatusCode int }

func (e *ControlPlaneStatusError) Error() string {
	return fmt.Sprintf("control-plane request failed: status %d", e.StatusCode)
}

// A connector must survive transport failures and control-plane 5xx responses:
// its stream has its own reconnect loop and the next heartbeat repairs
// liveness. A 4xx response is different — the persisted identity or request is
// rejected and retrying forever would hide an operator-actionable fault. 429 is
// transient backpressure, so it remains retryable.
func heartbeatRejected(err error) bool {
	var statusErr *ControlPlaneStatusError
	return errors.As(err, &statusErr) && statusErr.StatusCode >= 400 && statusErr.StatusCode < 500 && statusErr.StatusCode != http.StatusTooManyRequests
}

func (c *Client) request(ctx context.Context, method, path string, body any, credential string, out any) error {
	b, err := json.Marshal(body)
	if err != nil {
		return err
	}
	endpoint := strings.TrimRight(c.cfg.ControlPlaneURL, "/") + path
	req, err := http.NewRequestWithContext(ctx, method, endpoint, bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if credential != "" {
		req.Header.Set("Authorization", "Bearer "+credential)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("control-plane request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return &ControlPlaneStatusError{StatusCode: resp.StatusCode}
	}
	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			return fmt.Errorf("decode control-plane response: %w", err)
		}
	}
	return nil
}

// Redact removes secret values from user-visible error or status text.
func Redact(s string, secrets ...string) string {
	for _, secret := range secrets {
		if secret != "" {
			s = strings.ReplaceAll(s, secret, "[REDACTED]")
		}
	}
	return s
}
