package dataplane

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"time"

	usage "github.com/agentarea/agentarea/agentarea-go/internal/kernel/resourceusage"
)

// UsagePath is the data plane's owner-scoped usage route, relative to /dataplane/v1.
const UsagePath = "/usage"

const usageTimeout = 30 * time.Second

var _ usage.RuntimeSampler = (*Client)(nil)

// SampleUsage reads the data plane's usage route: its own workloads, scoped by
// its identity, never by anything the control plane sends.
func (c *Client) SampleUsage(ctx context.Context) ([]usage.Sample, error) {
	return c.sampleUsage(ctx, "")
}

// SampleResourceUsage reads one MCP instance's workloads from the data plane.
func (c *Client) SampleResourceUsage(ctx context.Context, resourceID string) ([]usage.Sample, error) {
	if resourceID == "" {
		return nil, fmt.Errorf("usage resource is required")
	}
	return c.sampleUsage(ctx, resourceID)
}

func (c *Client) sampleUsage(ctx context.Context, resourceID string) ([]usage.Sample, error) {
	ctx, cancel := context.WithTimeout(ctx, usageTimeout)
	defer cancel()
	var payload struct {
		Samples []usage.Sample `json:"samples"`
	}
	path := apiPrefix + UsagePath
	if resourceID != "" {
		path += "?resource_id=" + url.QueryEscape(resourceID)
	}
	if err := c.do(ctx, http.MethodGet, path, nil, &payload); err != nil {
		return nil, err
	}
	if payload.Samples == nil {
		return nil, fmt.Errorf("data plane omitted usage inventory")
	}
	return payload.Samples, nil
}
