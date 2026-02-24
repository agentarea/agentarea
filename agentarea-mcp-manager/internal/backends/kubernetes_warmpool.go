package backends

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"
)

// CreateInstanceWithWarmPool creates MCP instance using warm pool for fast activation
func (k *KubernetesBackend) CreateInstanceWithWarmPool(ctx context.Context, spec *InstanceSpec) (*InstanceResult, error) {
	instanceName := k.sanitizeInstanceName(spec.Name)

	k.logger.Info("Creating Kubernetes instance with warm pool",
		slog.String("name", spec.Name),
		slog.String("instance_name", instanceName))

	// Create ConfigMap and Secret first
	if err := k.createConfigMap(ctx, instanceName, spec); err != nil {
		return nil, fmt.Errorf("failed to create configmap: %w", err)
	}

	if err := k.createSecret(ctx, instanceName, spec); err != nil {
		k.cleanupResources(ctx, instanceName)
		return nil, fmt.Errorf("failed to create secret: %w", err)
	}

	// Try warm pool activation
	warmPoolClient := warmpool.NewClient(k.clientset, k.k8sConfig.Namespace)

	pod, err := warmPoolClient.FindAvailablePod(ctx)
	if err != nil {
		k.logger.Warn("No warm pods available, falling back to standard deployment",
			slog.String("error", err.Error()))
		return k.CreateInstance(ctx, spec)
	}

	k.logger.Info("Found warm pod",
		slog.String("pod", pod.Name),
		slog.String("node", pod.Spec.NodeName))

	// Create MCP instance model for activation
	instance := &models.MCPServerInstance{
		InstanceID: string(pod.UID),
		Name:       spec.Name,
		JSONSpec: map[string]interface{}{
			"image": spec.Image,
			"port":  spec.Port,
		},
	}

	// Assign pod to instance
	pod, err = warmPoolClient.AssignPod(ctx, pod, instance)
	if err != nil {
		return nil, fmt.Errorf("failed to assign warm pod: %w", err)
	}

	// Activate MCP inside pod
	activationReq := warmpool.ActivationRequest{
		MCPImage:     spec.Image,
		MCPImageHash: hashImage(spec.Image),
		Port:         spec.Port,
		Entrypoint:   spec.Entrypoint,
		Command:      spec.Command,
		Env:          spec.Environment,
	}

	k.logger.Info("Sending activation request",
		slog.Int("port", spec.Port),
		slog.String("image", spec.Image))

	if err := warmPoolClient.ActivatePod(ctx, pod, activationReq); err != nil {
		// Return pod to pool and fallback
		warmPoolClient.ReturnToPool(ctx, pod)
		k.logger.Error("Warm pool activation failed, falling back",
			slog.String("error", err.Error()))
		return k.CreateInstance(ctx, spec)
	}

	// Mark pod as ready
	pod, err = warmPoolClient.MarkReady(ctx, pod)
	if err != nil {
		return nil, fmt.Errorf("failed to mark pod ready: %w", err)
	}

	// Create Service pointing to this pod
	if err := k.createServiceForPod(ctx, instanceName, spec, pod); err != nil {
		warmPoolClient.ReturnToPool(ctx, pod)
		k.cleanupResources(ctx, instanceName)
		return nil, fmt.Errorf("failed to create service: %w", err)
	}

	// Create route for external access
	// Try Gateway API HTTPRoute first, fall back to Ingress if needed
	if err := k.createRoute(ctx, instanceName, spec); err != nil {
		k.cleanupResources(ctx, instanceName)
		return nil, fmt.Errorf("failed to create route: %w", err)
	}

	result := &InstanceResult{
		ID:          string(pod.UID),
		Name:        spec.Name,
		URL:         k.k8sConfig.GetInstanceURL(instanceName),
		InternalURL: k.k8sConfig.GetInternalServiceURL(instanceName, spec.Port),
		Status:      "running",
	}

	k.logger.Info("Successfully created Kubernetes instance via warm pool",
		slog.String("id", result.ID),
		slog.String("name", result.Name),
		slog.String("url", result.URL))

	return result, nil
}

// createServiceForPod creates a Service targeting a specific pod
func (k *KubernetesBackend) createServiceForPod(ctx context.Context, instanceName string, spec *InstanceSpec, pod *corev1.Pod) error {
	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels: map[string]string{
				"app.kubernetes.io/managed-by": "mcp-manager",
				"app.kubernetes.io/component":  "mcp-server",
				"app.kubernetes.io/instance":   instanceName,
				"agentarea.io/instance":        instanceName,
				"mcp.agentarea.io/warm-pod":    pod.Name,
			},
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Selector: map[string]string{
				"mcp.agentarea.io/instance-name": instanceName,
			},
			Ports: []corev1.ServicePort{
				{
					Name:       "mcp",
					Port:       int32(spec.Port),
					TargetPort: intstr.FromInt(spec.Port),
					Protocol:   corev1.ProtocolTCP,
				},
			},
		},
	}

	if err := k.client.Create(ctx, service); err != nil {
		return fmt.Errorf("failed to create service: %w", err)
	}

	return nil
}

// hashImage generates a hash for image caching
func hashImage(image string) string {
	// Simple hash - in production use SHA256
	return fmt.Sprintf("%x", image)[:16]
}
