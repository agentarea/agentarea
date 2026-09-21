package dataplane

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"time"

	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/gin-gonic/gin"
)

// Ownership filtering belongs inside the backend before sampling, not against a
// second, potentially stale inventory or against caller-supplied resource IDs.
type ownedUsageSampler interface {
	SampleUsageForOwner(context.Context, string) ([]usage.Sample, error)
}

type ownedResourceUsageSampler interface {
	SampleResourceUsageForOwner(context.Context, string, string) ([]usage.Sample, error)
}

func (s *Server) sampleUsage(c *gin.Context) {
	resourceIDs, targeted := c.Request.URL.Query()["resource_id"]
	if targeted && (len(resourceIDs) != 1 || resourceIDs[0] == "") {
		c.JSON(http.StatusBadRequest, gin.H{"error": "one nonempty resource_id is required"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	var samples []usage.Sample
	var err error
	if targeted {
		sampler, ok := s.backend.(ownedResourceUsageSampler)
		if !ok {
			c.JSON(http.StatusNotImplemented, gin.H{"error": "backend does not support owner-scoped resource usage sampling"})
			return
		}
		samples, err = sampler.SampleResourceUsageForOwner(ctx, s.cfg.AgentID, resourceIDs[0])
	} else {
		sampler, ok := s.backend.(ownedUsageSampler)
		if !ok {
			c.JSON(http.StatusNotImplemented, gin.H{"error": "backend does not support owner-scoped usage sampling"})
			return
		}
		samples, err = sampler.SampleUsageForOwner(ctx, s.cfg.AgentID)
	}
	if err != nil {
		s.logger.Error("Data plane usage sampling failed", slog.String("agent_id", s.cfg.AgentID), slog.String("error", err.Error()))
		c.JSON(http.StatusBadGateway, gin.H{"error": "runtime usage inventory unavailable"})
		return
	}
	if samples == nil {
		samples = []usage.Sample{}
	}
	c.JSON(http.StatusOK, gin.H{"samples": samples})
}

func (c *Client) SampleUsage(ctx context.Context) ([]usage.Sample, error) {
	return c.sampleUsage(ctx, "")
}

func (c *Client) SampleResourceUsage(ctx context.Context, resourceID string) ([]usage.Sample, error) {
	if resourceID == "" {
		return nil, fmt.Errorf("usage resource is required")
	}
	return c.sampleUsage(ctx, resourceID)
}

func (c *Client) sampleUsage(ctx context.Context, resourceID string) ([]usage.Sample, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	var payload struct {
		Samples []usage.Sample `json:"samples"`
	}
	// Decode directly into integer fields, never through map[string]any or a
	// float64 intermediate: counters routinely exceed JSON's safe float range.
	path := "/dataplane/v1/usage"
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
