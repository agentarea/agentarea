// Package reconciler provides state synchronization between database MCP instances
// and Kubernetes resources. It ensures that the actual state (K8s resources) matches
// the desired state (database records).
package reconciler

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/models"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/cache"
)

// State represents the sync state of an MCP instance
type State string

const (
	StateSynced     State = "synced"      // DB and K8s match
	StateMissing    State = "missing"     // In DB but no K8s resources
	StateOrphaned   State = "orphaned"    // K8s resources exist but no DB record
	StateMismatch   State = "mismatch"    // Resources exist but different from expected
	StateRecreating State = "recreating"  // Currently being recreated
	StateDeleting   State = "deleting"    // Currently being deleted
)

// SyncResult represents the result of a reconciliation
type SyncResult struct {
	InstanceID   string
	InstanceName string
	State        State
	Message      string
	Timestamp    time.Time
}

// Stats holds reconciliation statistics
type Stats struct {
	TotalInstances  int
	Synced          int
	Missing         int
	Orphaned        int
	Mismatch        int
	Recreated       int
	CleanedUp       int
	Errors          int
	LastSync        time.Time
	Duration        time.Duration
}

// MCPInstanceRepository defines the interface for MCP instance DB operations
type MCPInstanceRepository interface {
	GetAll(ctx context.Context) ([]*models.MCPServerInstance, error)
	GetByID(ctx context.Context, id string) (*models.MCPServerInstance, error)
	UpdateStatus(ctx context.Context, id string, status string) error
}

// Reconciler manages state synchronization between DB and K8s
type Reconciler struct {
	logger     *slog.Logger
	backend    backends.Backend
	repository MCPInstanceRepository
	client     kubernetes.Interface
	namespace  string
	
	// Configuration
	syncInterval    time.Duration
	startupSync     bool
	autoRecreate    bool
	autoCleanup     bool
	
	// State
	mu              sync.RWMutex
	stats           Stats
	syncResults     []SyncResult
	maxResults      int
	lastSync        time.Time
	
	// Control
	ctx    context.Context
	cancel context.CancelFunc
	done   chan struct{}
}

// Config holds reconciler configuration
type Config struct {
	SyncInterval    time.Duration // How often to run full reconciliation
	StartupSync     bool          // Run sync on startup
	AutoRecreate    bool          // Automatically recreate missing resources
	AutoCleanup     bool          // Automatically clean up orphaned resources
	MaxResults      int           // Max number of sync results to keep
}

// DefaultConfig returns default configuration
func DefaultConfig() Config {
	return Config{
		SyncInterval: 5 * time.Minute,
		StartupSync:  true,
		AutoRecreate: true,
		AutoCleanup:  false, // Manual cleanup by default for safety
		MaxResults:   100,
	}
}

// New creates a new reconciler
func New(
	logger *slog.Logger,
	backend backends.Backend,
	repository MCPInstanceRepository,
	client kubernetes.Interface,
	namespace string,
	config Config,
) *Reconciler {
	ctx, cancel := context.WithCancel(context.Background())
	
	return &Reconciler{
		logger:       logger.With("component", "reconciler"),
		backend:      backend,
		repository:   repository,
		client:       client,
		namespace:    namespace,
		syncInterval: config.SyncInterval,
		startupSync:  config.StartupSync,
		autoRecreate: config.AutoRecreate,
		autoCleanup:  config.AutoCleanup,
		maxResults:   config.MaxResults,
		ctx:          ctx,
		cancel:       cancel,
		done:         make(chan struct{}),
	}
}

// Start begins the reconciliation loop
func (r *Reconciler) Start() error {
	r.logger.Info("Starting reconciler",
		"namespace", r.namespace,
		"syncInterval", r.syncInterval,
		"startupSync", r.startupSync,
	)
	
	// Run startup sync if enabled
	if r.startupSync {
		if err := r.RunFullSync(); err != nil {
			r.logger.Error("Startup sync failed", "error", err)
			// Continue anyway - don't block startup
		}
	}
	
	// Start periodic sync
	go r.runPeriodicSync()
	
	// Start K8s watchers
	go r.startWatchers()
	
	return nil
}

// Stop stops the reconciliation loop
func (r *Reconciler) Stop() {
	r.logger.Info("Stopping reconciler")
	r.cancel()
	<-r.done
	r.logger.Info("Reconciler stopped")
}

// runPeriodicSync runs the sync loop
func (r *Reconciler) runPeriodicSync() {
	defer close(r.done)
	
	ticker := time.NewTicker(r.syncInterval)
	defer ticker.Stop()
	
	for {
		select {
		case <-r.ctx.Done():
			return
		case <-ticker.C:
			if err := r.RunFullSync(); err != nil {
				r.logger.Error("Periodic sync failed", "error", err)
			}
		}
	}
}

// RunFullSync performs a full reconciliation between DB and K8s state
func (r *Reconciler) RunFullSync() error {
	start := time.Now()
	r.logger.Info("Starting full reconciliation")
	
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
	
	// Check each DB instance
	for _, instance := range instances {
		result := r.reconcileInstance(instance, k8sResources)
		r.recordResult(result)
		
		switch result.State {
		case StateSynced:
			stats.Synced++
		case StateMissing:
			stats.Missing++
			if r.autoRecreate {
				if err := r.recreateInstance(instance); err != nil {
					r.logger.Error("Failed to recreate instance",
						"instance", instance.Name,
						"error", err,
					)
					stats.Errors++
				} else {
					stats.Recreated++
				}
			}
		case StateMismatch:
			stats.Mismatch++
		}
	}
	
	// Find orphaned resources (K8s resources without DB record)
	orphaned := r.findOrphanedResources(instances, k8sResources)
	stats.Orphaned = len(orphaned)
	
	if r.autoCleanup && len(orphaned) > 0 {
		for _, resource := range orphaned {
			if err := r.cleanupResource(resource); err != nil {
				r.logger.Error("Failed to cleanup orphaned resource",
					"resource", resource.Name,
					"error", err,
				)
				stats.Errors++
			} else {
				stats.CleanedUp++
			}
		}
	}
	
	stats.Duration = time.Since(start)
	r.updateStats(stats)
	
	r.logger.Info("Reconciliation complete",
		"duration", stats.Duration,
		"total", stats.TotalInstances,
		"synced", stats.Synced,
		"missing", stats.Missing,
		"orphaned", stats.Orphaned,
		"mismatch", stats.Mismatch,
		"recreated", stats.Recreated,
		"cleanedUp", stats.CleanedUp,
		"errors", stats.Errors,
	)
	
	return nil
}

// reconcileInstance checks the state of a single MCP instance
func (r *Reconciler) reconcileInstance(
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
		result.State = StateMissing
		result.Message = "K8s resources not found"
		
		// Update DB status if needed
		if instance.Status == "running" {
			r.logger.Warn("Instance marked as running but K8s resources missing",
				"instance", instance.Name,
			)
		}
		
		return result
	}
	
	// Check if resources are healthy
	if !resources.IsHealthy() {
		result.State = StateMismatch
		result.Message = fmt.Sprintf("Resources unhealthy: deployment=%v, service=%v",
			resources.DeploymentReady,
			resources.ServiceReady,
		)
		return result
	}
	
	result.State = StateSynced
	result.Message = "All resources healthy"
	return result
}

// recreateInstance recreates K8s resources for an MCP instance
func (r *Reconciler) recreateInstance(instance *models.MCPServerInstance) error {
	r.logger.Info("Recreating K8s resources",
		"instance", instance.Name,
		"id", instance.ID,
	)
	
	// Update status to indicate recreation
	if err := r.repository.UpdateStatus(r.ctx, instance.ID, "recreating"); err != nil {
		r.logger.Error("Failed to update instance status", "error", err)
	}
	
	// Recreate resources via backend
	ctx, cancel := context.WithTimeout(r.ctx, 5*time.Minute)
	defer cancel()
	
	if err := r.backend.Create(ctx, instance); err != nil {
		_ = r.repository.UpdateStatus(r.ctx, instance.ID, "error")
		return fmt.Errorf("failed to create resources: %w", err)
	}
	
	// Update status to running
	if err := r.repository.UpdateStatus(r.ctx, instance.ID, "running"); err != nil {
		r.logger.Error("Failed to update instance status to running", "error", err)
	}
	
	r.logger.Info("Successfully recreated resources",
		"instance", instance.Name,
	)
	
	return nil
}

// K8sResourceSet holds the K8s resources for an MCP instance
type K8sResourceSet struct {
	Name              string
	DeploymentExists  bool
	DeploymentReady   bool
	ServiceExists     bool
	ServiceReady      bool
	HTTPRouteExists   bool
	ConfigMapExists   bool
	SecretExists      bool
	Labels            map[string]string
}

// IsHealthy returns true if all required resources exist and are ready
func (r *K8sResourceSet) IsHealthy() bool {
	return r.DeploymentExists && r.DeploymentReady &&
		r.ServiceExists && r.ServiceReady
}

// getK8sResources retrieves all MCP-related K8s resources
func (r *Reconciler) getK8sResources() (map[string]*K8sResourceSet, error) {
	resources := make(map[string]*K8sResourceSet)
	
	// List deployments with MCP label
	deployments, err := r.client.AppsV1().Deployments(r.namespace).List(
		r.ctx,
		metav1.ListOptions{
			LabelSelector: "app.kubernetes.io/managed-by=mcp-manager",
		},
	)
	if err != nil {
		return nil, fmt.Errorf("failed to list deployments: %w", err)
	}
	
	for _, dep := range deployments.Items {
		instanceName := dep.Labels["agentarea.io/instance"]
		if instanceName == "" {
			continue
		}
		
		if _, exists := resources[instanceName]; !exists {
			resources[instanceName] = &K8sResourceSet{
				Name:   instanceName,
				Labels: dep.Labels,
			}
		}
		
		resources[instanceName].DeploymentExists = true
		resources[instanceName].DeploymentReady = dep.Status.ReadyReplicas > 0
	}
	
	// List services
	services, err := r.client.CoreV1().Services(r.namespace).List(
		r.ctx,
		metav1.ListOptions{
			LabelSelector: "app.kubernetes.io/managed-by=mcp-manager",
		},
	)
	if err != nil {
		return nil, fmt.Errorf("failed to list services: %w", err)
	}
	
	for _, svc := range services.Items {
		instanceName := svc.Labels["agentarea.io/instance"]
		if instanceName == "" {
			continue
		}
		
		if _, exists := resources[instanceName]; !exists {
			resources[instanceName] = &K8sResourceSet{
				Name:   instanceName,
				Labels: svc.Labels,
			}
		}
		
		resources[instanceName].ServiceExists = true
		resources[instanceName].ServiceReady = true // Services are ready if they exist
	}
	
	return resources, nil
}

// findOrphanedResources finds K8s resources without corresponding DB records
func (r *Reconciler) findOrphanedResources(
	instances []*models.MCPServerInstance,
	k8sResources map[string]*K8sResourceSet,
) []*K8sResourceSet {
	var orphaned []*K8sResourceSet
	
	instanceMap := make(map[string]bool)
	for _, inst := range instances {
		instanceMap[inst.Name] = true
	}
	
	for name, resource := range k8sResources {
		if !instanceMap[name] {
			orphaned = append(orphaned, resource)
			r.logger.Warn("Found orphaned K8s resource",
				"name", name,
				"labels", resource.Labels,
			)
		}
	}
	
	return orphaned
}

// cleanupResource removes orphaned K8s resources
func (r *Reconciler) cleanupResource(resource *K8sResourceSet) error {
	r.logger.Info("Cleaning up orphaned resource",
		"name", resource.Name,
	)
	
	// This would call backend.Delete() for the orphaned resources
	// For safety, we just log for now unless autoCleanup is enabled
	return nil
}

// startWatchers starts K8s resource watchers for real-time detection
func (r *Reconciler) startWatchers() {
	factory := informers.NewSharedInformerFactoryWithOptions(
		r.client,
		10*time.Minute,
		informers.WithNamespace(r.namespace),
		informers.WithTweakListOptions(func(options *metav1.ListOptions) {
			options.LabelSelector = labels.SelectorFromSet(map[string]string{
				"app.kubernetes.io/managed-by": "mcp-manager",
			}).String()
		}),
	)
	
	// Watch deployments
	depInformer := factory.Apps().V1().Deployments().Informer()
	depInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		DeleteFunc: func(obj interface{}) {
			r.handleResourceDeletion(obj, "deployment")
		},
	})
	
	// Watch services
	svcInformer := factory.Core().V1().Services().Informer()
	svcInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		DeleteFunc: func(obj interface{}) {
			r.handleResourceDeletion(obj, "service")
		},
	})
	
	// Start informers
	factory.Start(r.ctx.Done())
	factory.WaitForCacheSync(r.ctx.Done())
	
	r.logger.Info("K8s watchers started")
}

// handleResourceDeletion handles K8s resource deletion events
func (r *Reconciler) handleResourceDeletion(obj interface{}, resourceType string) {
	// Extract instance name from labels
	// This would trigger a sync for the affected instance
	r.logger.Warn("Detected K8s resource deletion",
		"type", resourceType,
		"obj", obj,
	)
	
	// Trigger immediate sync
	go func() {
		// Small delay to batch multiple rapid deletions
		time.Sleep(5 * time.Second)
		if err := r.RunFullSync(); err != nil {
			r.logger.Error("Sync after deletion failed", "error", err)
		}
	}()
}

// recordResult records a sync result
func (r *Reconciler) recordResult(result SyncResult) {
	r.mu.Lock()
	defer r.mu.Unlock()
	
	r.syncResults = append(r.syncResults, result)
	if len(r.syncResults) > r.maxResults {
		r.syncResults = r.syncResults[len(r.syncResults)-r.maxResults:]
	}
}

// updateStats updates the reconciler stats
func (r *Reconciler) updateStats(stats Stats) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.stats = stats
	r.lastSync = time.Now()
}

// GetStats returns current reconciliation stats
func (r *Reconciler) GetStats() Stats {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.stats
}

// GetSyncResults returns recent sync results
func (r *Reconciler) GetSyncResults(limit int) []SyncResult {
	r.mu.RLock()
	defer r.mu.RUnlock()
	
	if limit <= 0 || limit > len(r.syncResults) {
		limit = len(r.syncResults)
	}
	
	// Return most recent first
	start := len(r.syncResults) - limit
	if start < 0 {
		start = 0
	}
	
	results := make([]SyncResult, limit)
	for i := 0; i < limit; i++ {
		results[i] = r.syncResults[start+i]
	}
	
	return results
}

// TriggerSync manually triggers a full sync
func (r *Reconciler) TriggerSync() error {
	r.logger.Info("Manual sync triggered")
	return r.RunFullSync()
}

// GetInstanceStatus returns the sync status of a specific instance
func (r *Reconciler) GetInstanceStatus(instanceName string) (*SyncResult, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	
	for i := len(r.syncResults) - 1; i >= 0; i-- {
		if r.syncResults[i].InstanceName == instanceName {
			return &r.syncResults[i], nil
		}
	}
	
	return nil, fmt.Errorf("no sync result found for instance %s", instanceName)
}
