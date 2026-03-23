package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/features"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

// executeSandbox handles script execution requests.
// Production: routes to a warm pool pod.
// Dev (no K8s): routes to SANDBOX_EXECUTOR_URL (standalone sandbox container).
func (h *Handler) executeSandbox(c *gin.Context) {
	var req warmpool.ExecuteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":   "invalid_request",
			"message": err.Error(),
		})
		return
	}

	if req.ScriptContent == "" || req.ScriptName == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":   "invalid_request",
			"message": "script_content and script_name are required",
		})
		return
	}

	// Production path: warm pool
	if features.IsEnabled(features.WarmPool) {
		if k8sBackend, ok := h.backend.(*backends.KubernetesBackend); ok {
			if wpClient := k8sBackend.GetWarmPoolClient(); wpClient != nil {
				if pod, err := wpClient.FindAvailablePod(c.Request.Context()); err == nil {
					result, err := wpClient.ExecuteInPod(c.Request.Context(), pod, req)
					if err != nil {
						h.logger.Error("Warm pool execution failed", "error", err, "pod", pod.Name)
						c.JSON(http.StatusInternalServerError, gin.H{
							"error":   "execution_failed",
							"message": err.Error(),
						})
						return
					}
					c.JSON(http.StatusOK, result)
					return
				}
			}
		}
	}

	// Dev path: route to standalone sandbox executor container
	executorURL := os.Getenv("SANDBOX_EXECUTOR_URL")
	if executorURL == "" {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":   "no_executor",
			"message": "no warm pool or sandbox executor available (set SANDBOX_EXECUTOR_URL)",
		})
		return
	}

	result, err := forwardToExecutor(c, executorURL, req)
	if err != nil {
		h.logger.Error("Sandbox executor failed", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":   "execution_failed",
			"message": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, result)
}

// forwardToExecutor sends the execute request to a standalone sandbox executor container.
func forwardToExecutor(c *gin.Context, executorURL string, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	url := fmt.Sprintf("%s/execute", executorURL)

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	timeout := 30
	if req.TimeoutSeconds > 0 {
		timeout = req.TimeoutSeconds + 5
	}

	httpReq, err := http.NewRequestWithContext(c.Request.Context(), "POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: time.Duration(timeout) * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("executor request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("executor returned status %d", resp.StatusCode)
	}

	var result warmpool.ExecuteResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &result, nil
}
