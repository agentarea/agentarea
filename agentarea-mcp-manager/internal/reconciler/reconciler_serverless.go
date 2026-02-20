// Serverless mode support for reconciler
// In serverless mode, we don't force pods to be running - they're intentionally scaled to zero

package reconciler

import (
	"context"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ServerlessMode represents the scaling mode for an MCP instance
type ServerlessMode string

const (
	ServerlessModeAuto     ServerlessMode = "auto"      // Use KEDA/Knative
	ServerlessModeManual   ServerlessMode = "manual"    // MCP Manager controls scaling
	ServerlessModeDisabled ServerlessMode = "disabled"  // Always-on (traditional)
)

// ServerlessConfig holds serverless configuration for an MCP instance
type ServerlessConfig struct {
	Enabled          bool           `json:"enabled"`
	Mode             ServerlessMode `json:"mode"`
	IdleTimeout      time.Duration  `json:"idleTimeout"`
	MinReplicas      int32          `json:"minReplicas"`
	MaxReplicas      int32          `json:"maxReplicas"`
	MaxColdStartTime time.Duration  `json:"maxColdStartTime"`
}

// DefaultServerlessConfig returns default serverless configuration
func DefaultServerlessConfig() ServerlessConfig {
	return ServerlessConfig{
		Enabled:          true,
		Mode:             ServerlessModeAuto,
		IdleTimeout:      5 * time.Minute,
		MinReplicas:      0,
		MaxReplicas:      10,
		MaxColdStartTime: 30 * time.Second,
	}
}

// IsServerless returns true if the instance should run in serverless mode
func (r *Reconciler) IsServerless(instance *models.MCPServerInstance) bool {
	// Check instance spec for serverless config
	if instance.JSONSpec != nil {
		if serverlessInterface, exists := instance.JSONSpec["serverless"]; exists {
			if serverlessMap, ok := serverlessInterface.(map[string]interface{}); ok {
				if enabled, ok := serverlessMap["enabled"].(bool); ok {
					return enabled
				}
			}
		}
	}
	
	// Check global default
	// This would come from environment or config
	return r.getGlobalServerlessDefault()
}

// getGlobalServerlessDefault returns the global default for serverless mode
func (r *Reconciler) getGlobalServerlessDefault() bool {
	// TODO: Read from config or env var
	// For now, default to serverless
	return true
}

// reconcileServerlessInstance handles reconciliation for serverless MCP instances
// Key difference: We DON'T recreate pods that are scaled to zero - that's intentional
func (r *Reconciler) reconcileServerlessInstance(
	instance *models.MCPServerInstance,
	k8sResources map[string]*K8sResourceSet,
) SyncResult {
	result := SyncResult{
		InstanceID:   instance.ID,
		InstanceName: instance.Name,
		Timestamp:    time.Now(),
	}
	
	// Check if K8s resources exist
	resources, exists := k8sResources[instance.Name]
	if !exists {
		// Resources don't exist at all - need to create them
		result.State = StateMissing
		result.Message = "K8s resources not found - creating serverless resources"
		
		if r.autoRecreate {
			if err := r.createServerlessResources(instance); err != nil {
				result.State = StateError
				result.Message = fmt.Sprintf("Failed to create resources: %v", err)
			} else {
				result.State = StateCreated
				result.Message = "Serverless resources created (scaled to zero)"
			}
		}
		
		return result
	}
	
	// Resources exist - check their state
	// For serverless, 0 replicas is OK!
	if resources.DeploymentExists {
		// Get actual replica count
		replicas, err := r.getDeploymentReplicas(instance.Name)
		if err != nil {
			result.State = StateError
			result.Message = fmt.Sprintf("Failed to get replica count: %v", err)
			return result
		}
		
		if replicas == 0 {
			// This is expected for serverless!
			result.State = StateScaledToZero
			result.Message = "Scaled to zero (idle)"
			
			// Update DB status
			if instance.Status != "scaled-to-zero" {
				r.repository.UpdateStatus(r.ctx, instance.ID, "scaled-to-zero")
			}
			
			return result
		}
		
		if replicas > 0 && resources.DeploymentReady {
			result.State = StateReady
			result.Message = fmt.Sprintf("Running (%d replicas)", replicas)
			
			if instance.Status != "ready" {
				r.repository.UpdateStatus(r.ctx, instance.ID, "ready")
			}
			
			return result
		}
		
		// Deployment exists but not ready (scaling up/down)
		result.State = StateTransitioning
		result.Message = fmt.Sprintf("Scaling (%d replicas, not ready)", replicas)
		return result
	}
	
	// Deployment doesn't exist but other resources do
	result.State = StateMismatch
	result.Message = "Resources incomplete - deployment missing"
	
	return result
}

// createServerlessResources creates K8s resources for serverless mode
func (r *Reconciler) createServerlessResources(instance *models.MCPServerInstance) error {
	r.logger.Info("Creating serverless resources",
		"instance", instance.Name,
		"id", instance.ID,
	)
	
	// Get serverless config
	config := r.getServerlessConfig(instance)
	
	// 1. Create ConfigMap and Secret (same as always-on)
	// 2. Create Service (always needed, even with 0 endpoints)
	// 3. Create HTTPRoute with retry policy for cold start
	// 4. Create Deployment with 0 replicas initially
	// 5. Create ScaledObject (KEDA) or Knative Service
	
	ctx, cancel := context.WithTimeout(r.ctx, 5*time.Minute)
	defer cancel()
	
	// Use backend to create base resources
	if err := r.backend.Create(ctx, instance); err != nil {
		return fmt.Errorf("failed to create base resources: %w", err)
	}
	
	// Scale to zero
	if err := r.scaleDeployment(instance.Name, 0); err != nil {
		r.logger.Error("Failed to scale to zero, will retry later", "error", err)
	}
	
	// Create ScaledObject for serverless scaling
	if err := r.createScaledObject(instance, config); err != nil {
		r.logger.Error("Failed to create ScaledObject", "error", err)
		// Continue - MCP will work but won't scale to zero automatically
	}
	
	// Update status
	r.repository.UpdateStatus(r.ctx, instance.ID, "scaled-to-zero")
	
	r.logger.Info("Serverless resources created",
		"instance", instance.Name,
	)
	
	return nil
}

// getServerlessConfig extracts serverless config from instance spec
func (r *Reconciler) getServerlessConfig(instance *models.MCPServerInstance) ServerlessConfig {
	config := DefaultServerlessConfig()
	
	if instance.JSONSpec == nil {
		return config
	}
	
	serverlessInterface, exists := instance.JSONSpec["serverless"]
	if !exists {
		return config
	}
	
	serverlessMap, ok := serverlessInterface.(map[string]interface{})
	if !ok {
		return config
	}
	
	// Parse config values
	if enabled, ok := serverlessMap["enabled"].(bool); ok {
		config.Enabled = enabled
	}
	if minReplicas, ok := serverlessMap["minReplicas"].(float64); ok {
		config.MinReplicas = int32(minReplicas)
	}
	if maxReplicas, ok := serverlessMap["maxReplicas"].(float64); ok {
		config.MaxReplicas = int32(maxReplicas)
	}
	
	return config
}

// getDeploymentReplicas gets the current replica count for a deployment
func (r *Reconciler) getDeploymentReplicas(name string) (int32, error) {
	deployment, err := r.client.AppsV1().Deployments(r.namespace).Get(
		r.ctx,
		"mcp-"+name,
		metav1.GetOptions{},
	)
	if err != nil {
		return 0, err
	}
	
	if deployment.Spec.Replicas != nil {
		return *deployment.Spec.Replicas, nil
	}
	return 0, nil
}

// scaleDeployment scales a deployment to the specified replica count
func (r *Reconciler) scaleDeployment(name string, replicas int32) error {
	deployment, err := r.client.AppsV1().Deployments(r.namespace).Get(
		r.ctx,
		"mcp-"+name,
		metav1.GetOptions{},
	)
	if err != nil {
		return err
	}
	
	deployment.Spec.Replicas = &replicas
	_, err = r.client.AppsV1().Deployments(r.namespace).Update(
		r.ctx,
		deployment,
		metav1.UpdateOptions{},
	)
	return err
}

// createScaledObject creates a KEDA ScaledObject for the MCP instance
func (r *Reconciler) createScaledObject(instance *models.MCPServerInstance, config ServerlessConfig) error {
	// This would create a KEDA ScaledObject
	// For now, log that we would create it
	r.logger.Info("Would create ScaledObject",
		"instance", instance.Name,
		"minReplicas", config.MinReplicas,
		"maxReplicas", config.MaxReplicas,
	)
	
	// TODO: Implement actual ScaledObject creation
	// This requires the keda.sh/v1alpha1 client
	
	return nil
}

// Additional states for serverless mode
const (
	StateScaledToZero   State = "scaled-to-zero"   // Intentionally at 0 replicas
	StateReady          State = "ready"            // Running and ready
	StateTransitioning  State = "scaling"          // Scaling up/down
	StateCreated        State = "created"          // Resources created
	StateError          State = "error"            // Error state
)

// Modified RunFullSync to handle serverless instances
func (r *Reconciler) RunFullSyncWithServerless() error {
	start := time.Now()
	r.logger.Info("Starting full reconciliation (with serverless support)")
	
	// Get all MCP instances from DB
	instances, err := r.repository.GetAll(r.ctx)
	if err != nil {
		return fmt.Errorf("failed to get MCP instances from DB: %w", err)
	}
	
	// Get all MCP-related K8s resources
	k8sResources, err := r.getK8sResources()
	if err != nil {
		return fmt.Errorf("failed to get K8s resources: %w", err)
	}
	
	// Calculate stats
	stats := Stats{
		TotalInstances: len(instances),
		LastSync:       start,
	}
	
	// Check each instance
	for _, instance := range instances {
		var result SyncResult
		
		if r.IsServerless(instance) {
			result = r.reconcileServerlessInstance(instance, k8sResources)
		} else {
			result = r.reconcileInstance(instance, k8sResources)
		}
		
		r.recordResult(result)
		
		// Update stats based on state
		switch result.State {
		case StateSynced, StateReady:
			stats.Synced++
		case StateScaledToZero:
			// Serverless - this is OK, not an error
			stats.Synced++
		case StateMissing:
			stats.Missing++
		case StateMismatch:
			stats.Mismatch++
		case StateError:
			stats.Errors++
		}
	}
	
	// Find orphaned resources
	orphaned := r.findOrphanedResources(instances, k8sResources)
	stats.Orphaned = len(orphaned)
	
	stats.Duration = time.Since(start)
	r.updateStats(stats)
	
	r.logger.Info("Reconciliation complete",
		"duration", stats.Duration,
		"total", stats.TotalInstances,
		"synced", stats.Synced,
		"missing", stats.Missing,
		"orphaned", stats.Orphaned,
		"mismatch", stats.Mismatch,
		"errors", stats.Errors,
	)
	
	return nil
}
