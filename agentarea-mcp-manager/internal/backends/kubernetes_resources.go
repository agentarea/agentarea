package backends

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// createConfigMap creates a ConfigMap for the MCP instance
func (k *KubernetesBackend) createConfigMap(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    k.getCommonLabels(instanceName),
		},
		Data: map[string]string{
			"instance-id":  spec.InstanceID,
			"service-name": spec.ServiceName,
			"port":         strconv.Itoa(spec.Port),
			"workspace-id": spec.WorkspaceID,
		},
	}

	if err := k.client.Create(ctx, configMap); err != nil {
		return fmt.Errorf("failed to create configmap: %w", err)
	}

	return nil
}

// createSecret creates a Secret for environment variables
func (k *KubernetesBackend) createSecret(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	secretData := make(map[string][]byte)

	// Add environment variables
	for key, value := range spec.Environment {
		secretData[key] = []byte(value)
	}

	// Add MCP-specific environment variables
	secretData["MCP_INSTANCE_ID"] = []byte(spec.InstanceID)
	secretData["MCP_SERVICE_NAME"] = []byte(spec.ServiceName)
	secretData["MCP_CONTAINER_PORT"] = []byte(strconv.Itoa(spec.Port))

	secret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    k.getCommonLabels(instanceName),
		},
		Type: corev1.SecretTypeOpaque,
		Data: secretData,
	}

	if err := k.client.Create(ctx, secret); err != nil {
		return fmt.Errorf("failed to create secret: %w", err)
	}

	return nil
}

// createDeployment creates a Deployment for the MCP server
// applyQuantities parses caller-supplied resource strings into a ResourceList.
//
// resource.MustParse panics on malformed input, and these values ride in an
// instance spec that crosses from the platform API: one bad string from any
// workspace would take the manager down for every tenant on it.
func applyQuantities(into corev1.ResourceList, cpu, memory string) error {
	for name, value := range map[corev1.ResourceName]string{
		corev1.ResourceCPU:    cpu,
		corev1.ResourceMemory: memory,
	} {
		if value == "" {
			continue
		}
		parsed, err := resource.ParseQuantity(value)
		if err != nil {
			return fmt.Errorf("%s %q is not a valid quantity: %w", name, value, err)
		}
		if parsed.Sign() <= 0 {
			return fmt.Errorf("%s %q must be positive", name, value)
		}
		into[name] = parsed
	}
	return nil
}

// ceilingWithin refuses a workload asking for more than the operator allows. The
// requested ceiling is caller input, so it may only lower the operator's limit,
// never raise it.
func ceilingWithin(allowed, requested config.ResourceRequirements) error {
	for name, pair := range map[corev1.ResourceName][2]string{
		corev1.ResourceCPU:    {requested.CPU, allowed.CPU},
		corev1.ResourceMemory: {requested.Memory, allowed.Memory},
	} {
		want, ceiling := pair[0], pair[1]
		if want == "" {
			continue
		}
		wantQuantity, err := resource.ParseQuantity(want)
		if err != nil {
			return fmt.Errorf("%s %q is not a valid quantity: %w", name, want, err)
		}
		// A limit was asked for and the deployment cannot say what it allows. The
		// safe reading of a missing or unusable ceiling is "not this", not
		// "anything": otherwise one bad configuration value silently returns the
		// decision to whoever fills in the spec.
		if ceiling == "" {
			return fmt.Errorf("no %s ceiling is configured, refusing the requested %s", name, want)
		}
		ceilingQuantity, err := resource.ParseQuantity(ceiling)
		if err != nil {
			return fmt.Errorf("configured %s ceiling %q is unusable, refusing the requested %s: %w",
				name, ceiling, want, err)
		}
		if wantQuantity.Cmp(ceilingQuantity) > 0 {
			return fmt.Errorf("requested %s %s exceeds the %s this deployment allows", name, want, ceiling)
		}
	}
	return nil
}

func (k *KubernetesBackend) createDeployment(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	// Operator labels first, platform labels (incl. the managed-by label the
	// egress NetworkPolicy selects on) applied on top so they can't be clobbered.
	labels := mergeStringMaps(k.k8sConfig.InstancePod.Labels, k.getCommonLabels(instanceName))

	// Convert ResourceList to config.ResourceRequirements
	var configRequests, configLimits *config.ResourceRequirements
	if spec.Resources.Requests.CPU != "" || spec.Resources.Requests.Memory != "" {
		configRequests = &config.ResourceRequirements{
			CPU:    spec.Resources.Requests.CPU,
			Memory: spec.Resources.Requests.Memory,
		}
	}
	if spec.Resources.Limits.CPU != "" || spec.Resources.Limits.Memory != "" {
		configLimits = &config.ResourceRequirements{
			CPU:    spec.Resources.Limits.CPU,
			Memory: spec.Resources.Limits.Memory,
		}
	}

	// Resource requirements
	requests := k.k8sConfig.GetResourceRequirements(configRequests, nil)
	limits := k.k8sConfig.GetResourceLimits(configLimits)

	resourceRequirements := corev1.ResourceRequirements{
		Requests: corev1.ResourceList{},
		Limits:   corev1.ResourceList{},
	}

	if err := applyQuantities(resourceRequirements.Requests, requests.CPU, requests.Memory); err != nil {
		return fmt.Errorf("resource requests: %w", err)
	}
	if err := applyQuantities(resourceRequirements.Limits, limits.CPU, limits.Memory); err != nil {
		return fmt.Errorf("resource limits: %w", err)
	}
	if err := ceilingWithin(k.k8sConfig.GetResourceLimits(nil), limits); err != nil {
		return err
	}

	// Resolve the workload's isolation tier and apply it on top of the
	// operator's configured context. The tier may only tighten: the operator
	// hardens the whole cluster, a tier hardens one workload further.
	isolation, err := resolveSpecIsolation(spec, k.config.Container.DefaultIsolationTier)
	if err != nil {
		return err
	}

	readOnlyRoot := k.k8sConfig.SecurityContext.ReadOnlyRootFilesystem || isolation.ReadOnlyRootFilesystem
	allowPrivilegeEscalation := k.k8sConfig.SecurityContext.AllowPrivilegeEscalation && !isolation.NoNewPrivileges

	// Security context
	securityContext := &corev1.SecurityContext{
		RunAsNonRoot:             &k.k8sConfig.SecurityContext.RunAsNonRoot,
		RunAsUser:                &k.k8sConfig.SecurityContext.RunAsUser,
		ReadOnlyRootFilesystem:   &readOnlyRoot,
		AllowPrivilegeEscalation: &allowPrivilegeEscalation,
		Capabilities: &corev1.Capabilities{
			Drop: []corev1.Capability{},
		},
	}

	for _, cap := range tightenDropCapabilities(k.k8sConfig.SecurityContext.DropCapabilities, isolation) {
		securityContext.Capabilities.Drop = append(securityContext.Capabilities.Drop, corev1.Capability(cap))
	}

	// Container definition
	pullPolicy := k.k8sConfig.ImagePullPolicy
	if pullPolicy == "" {
		pullPolicy = "IfNotPresent" // safe default for k3d/local; production should set Always
	}
	container := corev1.Container{
		Name:            "mcp-server",
		Image:           spec.Image,
		ImagePullPolicy: corev1.PullPolicy(pullPolicy),
		Ports: []corev1.ContainerPort{
			{
				Name:          "http",
				ContainerPort: int32(spec.Port),
				Protocol:      corev1.ProtocolTCP,
			},
		},
		EnvFrom: []corev1.EnvFromSource{
			{
				SecretRef: &corev1.SecretEnvSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: fmt.Sprintf("mcp-%s", instanceName),
					},
				},
			},
			{
				ConfigMapRef: &corev1.ConfigMapEnvSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: fmt.Sprintf("mcp-%s", instanceName),
					},
				},
			},
		},
		Resources:       resourceRequirements,
		SecurityContext: securityContext,
		// TCP probes — portable across all MCP server images. HTTP probes
		// would require every image to implement the same /health path,
		// which is not part of the MCP spec.
		LivenessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				TCPSocket: &corev1.TCPSocketAction{Port: intstr.FromInt(spec.Port)},
			},
			InitialDelaySeconds: 30,
			PeriodSeconds:       10,
			TimeoutSeconds:      5,
			FailureThreshold:    3,
		},
		// Scale-to-zero means every call may pay this. A fixed initial delay is
		// dead time the fastest image cannot avoid, so slow starts are absorbed by
		// startupProbe's budget instead and readiness polls at one second.
		StartupProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				TCPSocket: &corev1.TCPSocketAction{Port: intstr.FromInt(spec.Port)},
			},
			PeriodSeconds:    1,
			TimeoutSeconds:   2,
			FailureThreshold: 120,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				TCPSocket: &corev1.TCPSocketAction{Port: intstr.FromInt(spec.Port)},
			},
			PeriodSeconds:    1,
			TimeoutSeconds:   2,
			FailureThreshold: 5,
		},
	}

	// Entrypoint → container.command (overrides image ENTRYPOINT).
	// Command   → container.args    (appended to ENTRYPOINT).
	if len(spec.Entrypoint) > 0 {
		container.Command = spec.Entrypoint
	}
	if len(spec.Command) > 0 {
		// Strip --transport=stdio: in K8s the pod must bind a port directly
		// (no traefik wrapper), and stdio-capable images default to HTTP SSE.
		args := make([]string, 0, len(spec.Command))
		for _, a := range spec.Command {
			if a != "--transport=stdio" {
				args = append(args, a)
			}
		}
		if len(args) > 0 {
			container.Args = args
		}
	}

	// Volume mounts for writable directories (since we use read-only root filesystem)
	volumeMounts := make([]corev1.VolumeMount, 0, 2+len(spec.WritablePaths))
	volumeMounts = append(volumeMounts,
		corev1.VolumeMount{
			Name:      "tmp",
			MountPath: "/tmp",
		},
		corev1.VolumeMount{
			Name:      "var-run",
			MountPath: "/var/run",
		},
	)

	// Add user-specified writable paths
	for i, path := range spec.WritablePaths {
		volumeName := fmt.Sprintf("writable-%d", i)
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      volumeName,
			MountPath: path,
		})
	}

	container.VolumeMounts = volumeMounts

	// Determine runtime class. The operator-configured class wins: a caller may
	// only choose a runtime class when none is enforced cluster-wide, so a request
	// can never downgrade away a sandbox runtime (e.g. gVisor/Kata) set by config.
	runtimeClassName := tightenRuntimeClass(k.k8sConfig.RuntimeClass, isolation, spec.RuntimeClass)

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    labels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: int32Ptr(1),
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{
					"app.kubernetes.io/name":     "mcp-server",
					"app.kubernetes.io/instance": instanceName,
				},
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: func() corev1.PodSpec {
					spec := corev1.PodSpec{
						SecurityContext: &corev1.PodSecurityContext{
							RunAsNonRoot: &k.k8sConfig.SecurityContext.RunAsNonRoot,
							RunAsUser:    &k.k8sConfig.SecurityContext.RunAsUser,
							// Restrict the syscall surface; untrusted MCP images
							// should not have unfiltered kernel access.
							SeccompProfile: &corev1.SeccompProfile{
								Type: corev1.SeccompProfileTypeRuntimeDefault,
							},
						},
						Containers: []corev1.Container{container},
						Volumes:    k.createVolumes(spec),
						// MCP servers proxy external upstreams and never call the
						// kube-apiserver; withholding the SA token means a hostile
						// image cannot use it to reach the control plane.
						AutomountServiceAccountToken: boolPtr(false),
						// Nothing is flushed on the way out — the workload holds no
						// durable state — so the default 30s only keeps a reaped
						// instance occupying its name and quota.
						TerminationGracePeriodSeconds: int64Ptr(5),
					}
					if k.k8sConfig.PodServiceAccountName != "" {
						spec.ServiceAccountName = k.k8sConfig.PodServiceAccountName
					}
					// Only set RuntimeClassName if it's not empty
					if runtimeClassName != "" {
						spec.RuntimeClassName = &runtimeClassName
					}
					// Operator-supplied scheduling/placement. These have no platform
					// security invariant to protect, so they apply as-is.
					ip := k.k8sConfig.InstancePod
					if len(ip.NodeSelector) > 0 {
						spec.NodeSelector = ip.NodeSelector
					}
					if len(ip.Tolerations) > 0 {
						spec.Tolerations = ip.Tolerations
					}
					if ip.Affinity != nil {
						spec.Affinity = ip.Affinity
					}
					if ip.PriorityClassName != "" {
						spec.PriorityClassName = ip.PriorityClassName
					}
					for _, name := range ip.ImagePullSecrets {
						spec.ImagePullSecrets = append(spec.ImagePullSecrets, corev1.LocalObjectReference{Name: name})
					}
					return spec
				}(),
			},
		},
	}

	// Operator annotations first, platform annotations applied on top (win).
	annotations := mergeStringMaps(k.k8sConfig.InstancePod.Annotations, map[string]string{
		"agentarea.io/instance-id":  spec.InstanceID,
		"agentarea.io/workspace-id": spec.WorkspaceID,
	})
	deployment.Spec.Template.Annotations = annotations

	if err := k.client.Create(ctx, deployment); err != nil {
		return fmt.Errorf("failed to create deployment: %w", err)
	}

	return nil
}

// createVolumes creates the volume specifications for writable directories.
//
// Every volume is bounded. An MCP workload keeps nothing across a restart, so
// unbounded scratch buys the instance nothing and lets one image exhaust the
// node's ephemeral storage for every other pod scheduled there.
func (k *KubernetesBackend) createVolumes(spec *InstanceSpec) []corev1.Volume {
	scratchLimit := k.scratchSizeLimit

	// Default volumes (always needed for security)
	volumes := make([]corev1.Volume, 0, 2+len(spec.WritablePaths))
	volumes = append(volumes,
		corev1.Volume{
			Name: "tmp",
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{SizeLimit: &scratchLimit},
			},
		},
		corev1.Volume{
			Name: "var-run",
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{SizeLimit: &scratchLimit},
			},
		},
	)

	// Add user-specified writable paths as EmptyDir volumes
	for i := range spec.WritablePaths {
		volumeName := fmt.Sprintf("writable-%d", i)
		volumes = append(volumes, corev1.Volume{
			Name: volumeName,
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{SizeLimit: &scratchLimit},
			},
		})
	}

	return volumes
}

// createService creates a Service for the MCP server
func (k *KubernetesBackend) createService(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	service := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      fmt.Sprintf("mcp-%s", instanceName),
			Namespace: k.k8sConfig.Namespace,
			Labels:    k.getCommonLabels(instanceName),
		},
		Spec: corev1.ServiceSpec{
			Selector: map[string]string{
				"app.kubernetes.io/name":     "mcp-server",
				"app.kubernetes.io/instance": instanceName,
			},
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       80,
					TargetPort: intstr.FromInt(spec.Port),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Type: corev1.ServiceTypeClusterIP,
		},
	}

	// Add metrics port if monitoring is enabled
	if k.k8sConfig.Monitoring.Enabled {
		service.Spec.Ports = append(service.Spec.Ports, corev1.ServicePort{
			Name:       "metrics",
			Port:       int32(k.k8sConfig.Monitoring.Metrics.Port),
			TargetPort: intstr.FromInt(k.k8sConfig.Monitoring.Metrics.Port),
			Protocol:   corev1.ProtocolTCP,
		})
	}

	if err := k.client.Create(ctx, service); err != nil {
		return fmt.Errorf("failed to create service: %w", err)
	}

	return nil
}

// cleanupResources removes all resources for an instance
func (k *KubernetesBackend) cleanupResources(ctx context.Context, instanceName string) error {
	resourceName := fmt.Sprintf("mcp-%s", instanceName)

	// Delete resources in reverse order. Instances are reachable only through
	// the demand gateway, so no Ingress or HTTPRoute is ever created for them
	// and none is cleaned up here.
	resources := []client.Object{
		&corev1.Service{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&appsv1.Deployment{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
		&corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      resourceName,
				Namespace: k.k8sConfig.Namespace,
			},
		},
	}

	var lastError error
	for _, resource := range resources {
		if err := k.client.Delete(ctx, resource); err != nil && !errors.IsNotFound(err) {
			k.logger.Warn("Failed to delete resource",
				slog.String("resource", fmt.Sprintf("%T", resource)),
				slog.String("name", resourceName),
				slog.String("error", err.Error()))
			lastError = err
		}
	}

	warmPods := &corev1.PodList{}
	if err := k.client.List(ctx, warmPods, client.InNamespace(k.k8sConfig.Namespace), client.MatchingLabels{
		"mcp.agentarea.io/instance-name": instanceName,
	}); err != nil {
		k.logger.Warn("Failed to list warm pods for cleanup",
			slog.String("instance_name", instanceName),
			slog.String("error", err.Error()))
		lastError = err
	} else {
		for _, pod := range warmPods.Items {
			if err := k.client.Delete(ctx, &pod); err != nil && !errors.IsNotFound(err) {
				k.logger.Warn("Failed to delete warm pod",
					slog.String("pod", pod.Name),
					slog.String("instance_name", instanceName),
					slog.String("error", err.Error()))
				lastError = err
			}
		}
	}

	return lastError
}

// Update methods

// updateConfigMap updates the ConfigMap for an instance
func (k *KubernetesBackend) updateConfigMap(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	configMap := &corev1.ConfigMap{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, configMap); err != nil {
		return fmt.Errorf("failed to get configmap: %w", err)
	}

	// Update data
	configMap.Data["port"] = strconv.Itoa(spec.Port)
	configMap.Data["workspace-id"] = spec.WorkspaceID

	if err := k.client.Update(ctx, configMap); err != nil {
		return fmt.Errorf("failed to update configmap: %w", err)
	}

	return nil
}

// updateSecret updates the Secret for an instance
func (k *KubernetesBackend) updateSecret(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	secret := &corev1.Secret{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, secret); err != nil {
		return fmt.Errorf("failed to get secret: %w", err)
	}

	// Update data
	secretData := make(map[string][]byte)
	for key, value := range spec.Environment {
		secretData[key] = []byte(value)
	}
	secretData["MCP_INSTANCE_ID"] = []byte(spec.InstanceID)
	secretData["MCP_SERVICE_NAME"] = []byte(spec.ServiceName)
	secretData["MCP_CONTAINER_PORT"] = []byte(strconv.Itoa(spec.Port))

	secret.Data = secretData

	if err := k.client.Update(ctx, secret); err != nil {
		return fmt.Errorf("failed to update secret: %w", err)
	}

	return nil
}

// updateDeployment updates the Deployment for an instance
func (k *KubernetesBackend) updateDeployment(ctx context.Context, instanceName string, spec *InstanceSpec) error {
	deployment := &appsv1.Deployment{}
	if err := k.client.Get(ctx, types.NamespacedName{
		Namespace: k.k8sConfig.Namespace,
		Name:      fmt.Sprintf("mcp-%s", instanceName),
	}, deployment); err != nil {
		return fmt.Errorf("failed to get deployment: %w", err)
	}

	// Update container image and command if needed
	if len(deployment.Spec.Template.Spec.Containers) > 0 {
		container := &deployment.Spec.Template.Spec.Containers[0]
		container.Image = spec.Image

		if len(spec.Entrypoint) > 0 {
			container.Command = spec.Entrypoint
		}
		if len(spec.Command) > 0 {
			container.Args = spec.Command
		}

		// Convert ResourceList to config.ResourceRequirements
		var configRequests, configLimits *config.ResourceRequirements
		if spec.Resources.Requests.CPU != "" || spec.Resources.Requests.Memory != "" {
			configRequests = &config.ResourceRequirements{
				CPU:    spec.Resources.Requests.CPU,
				Memory: spec.Resources.Requests.Memory,
			}
		}
		if spec.Resources.Limits.CPU != "" || spec.Resources.Limits.Memory != "" {
			configLimits = &config.ResourceRequirements{
				CPU:    spec.Resources.Limits.CPU,
				Memory: spec.Resources.Limits.Memory,
			}
		}

		// Update resource requirements
		requests := k.k8sConfig.GetResourceRequirements(configRequests, nil)
		limits := k.k8sConfig.GetResourceLimits(configLimits)

		if err := applyQuantities(container.Resources.Requests, requests.CPU, requests.Memory); err != nil {
			return fmt.Errorf("resource requests: %w", err)
		}
		if err := applyQuantities(container.Resources.Limits, limits.CPU, limits.Memory); err != nil {
			return fmt.Errorf("resource limits: %w", err)
		}
		if err := ceilingWithin(k.k8sConfig.GetResourceLimits(nil), limits); err != nil {
			return err
		}
	}

	// Update annotations to trigger rolling update
	if deployment.Spec.Template.Annotations == nil {
		deployment.Spec.Template.Annotations = make(map[string]string)
	}
	deployment.Spec.Template.Annotations["agentarea.io/updated-at"] = time.Now().Format(time.RFC3339)

	if err := k.client.Update(ctx, deployment); err != nil {
		return fmt.Errorf("failed to update deployment: %w", err)
	}

	return nil
}

// Helper functions

// findInstanceNameByID finds instance name by deployment UID or instance ID
func (k *KubernetesBackend) findInstanceNameByID(ctx context.Context, instanceID string) (string, error) {
	deployments := &appsv1.DeploymentList{}
	if err := k.client.List(ctx, deployments, client.InNamespace(k.k8sConfig.Namespace), client.MatchingLabels{
		"app.kubernetes.io/managed-by": "mcp-manager",
	}); err != nil {
		return "", fmt.Errorf("failed to list deployments: %w", err)
	}

	for _, deployment := range deployments.Items {
		// Check if UID matches
		if string(deployment.UID) == instanceID {
			return strings.TrimPrefix(deployment.Name, "mcp-"), nil
		}

		// Check if instance ID matches from annotations
		if annotations := deployment.Spec.Template.Annotations; annotations != nil {
			if mcpInstanceID, exists := annotations["agentarea.io/instance-id"]; exists {
				if mcpInstanceID == instanceID {
					return strings.TrimPrefix(deployment.Name, "mcp-"), nil
				}
			}
		}
	}

	configMaps := &corev1.ConfigMapList{}
	if err := k.client.List(ctx, configMaps, client.InNamespace(k.k8sConfig.Namespace), client.MatchingLabels{
		"app.kubernetes.io/managed-by": "mcp-manager",
		"app.kubernetes.io/component":  "mcp-server",
	}); err != nil {
		return "", fmt.Errorf("failed to list configmaps: %w", err)
	}
	for _, configMap := range configMaps.Items {
		if configMap.Data["instance-id"] == instanceID {
			return strings.TrimPrefix(configMap.Name, "mcp-"), nil
		}
	}

	return "", fmt.Errorf("%w: %s", ErrInstanceNotFound, instanceID)
}

// getDeploymentStatus determines status from deployment conditions
func (k *KubernetesBackend) getDeploymentStatus(deployment *appsv1.Deployment) string {
	if deployment.Status.ReadyReplicas == 0 {
		return "starting"
	}

	if deployment.Status.ReadyReplicas < deployment.Status.Replicas {
		return "partial"
	}

	if deployment.Status.ReadyReplicas == deployment.Status.Replicas {
		return "running"
	}

	// Check conditions for more specific status
	for _, condition := range deployment.Status.Conditions {
		if condition.Type == appsv1.DeploymentProgressing {
			if condition.Status == corev1.ConditionFalse {
				return "error"
			}
		}
	}

	return "unknown"
}

// performHTTPHealthCheck performs HTTP health check against the service.
// ctx is intentionally unused — the http.Client's own timeout governs the request.
func (k *KubernetesBackend) performHTTPHealthCheck(_ context.Context, instanceName string) (bool, time.Duration) {
	url := fmt.Sprintf("http://mcp-%s.%s.svc.cluster.local/health", instanceName, k.k8sConfig.Namespace)

	start := time.Now()
	client := &http.Client{Timeout: 10 * time.Second}

	resp, err := client.Get(url)
	responseTime := time.Since(start)

	if err != nil {
		return false, responseTime
	}
	defer resp.Body.Close()

	return resp.StatusCode >= 200 && resp.StatusCode < 300, responseTime
}

// Helper function for int32 pointer
func int64Ptr(i int64) *int64 {
	return &i
}

func int32Ptr(i int32) *int32 {
	return &i
}

// Helper function for bool pointer
func boolPtr(b bool) *bool {
	return &b
}

// mergeStringMaps returns base overlaid with override; override keys win. Used to
// apply operator-supplied labels/annotations while guaranteeing platform-managed
// keys cannot be clobbered (platform map is passed as override).
func mergeStringMaps(base, override map[string]string) map[string]string {
	out := make(map[string]string, len(base)+len(override))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range override {
		out[k] = v
	}
	return out
}
