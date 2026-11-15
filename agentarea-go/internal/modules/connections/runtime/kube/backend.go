package kube

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/client-go/kubernetes"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

const (
	managedByLabel = "app.kubernetes.io/managed-by"
	// managedByValue is kept from mcp-manager: running workloads carry it and
	// the chart's egress NetworkPolicy selects on it.
	managedByValue      = "mcp-manager"
	componentLabel      = "app.kubernetes.io/component"
	componentValue      = "mcp-server"
	instanceIDKey       = "agentarea.io/instance-id"
	workspaceIDKey      = "agentarea.io/workspace-id"
	serverContainerName = "mcp-server"
	// DataPlaneOwnerLabel marks a workload as owned by one data plane; the
	// authenticated data plane stamps it, never an operator default.
	DataPlaneOwnerLabel = "agentarea.io/dataplane-id"
	// EgressLabel moves an instance pod out of the default egress policy; only
	// the platform-assembled spec sets it.
	EgressLabel = "agentarea.io/egress"
)

// Backend runs MCP workloads as Kubernetes resources.
type Backend struct {
	client  kubernetes.Interface
	cfg     Config
	scratch resource.Quantity
	log     *slog.Logger
}

var _ workload.Backend = (*Backend)(nil)

// New connects to the execution cluster cfg names.
func New(cfg Config, log *slog.Logger) (*Backend, error) {
	rc, err := clusterConfig(cfg.Kubeconfig, log)
	if err != nil {
		return nil, err
	}
	cs, err := kubernetes.NewForConfig(rc)
	if err != nil {
		return nil, fmt.Errorf("kubernetes clientset: %w", err)
	}
	return NewWithClient(cfg, cs, log)
}

// NewWithClient runs workloads through client.
func NewWithClient(cfg Config, client kubernetes.Interface, log *slog.Logger) (*Backend, error) {
	if err := cfg.validate(); err != nil {
		return nil, fmt.Errorf("kubernetes backend: %w", err)
	}
	scratch, err := cfg.scratchSizeLimit()
	if err != nil {
		return nil, err
	}
	return &Backend{client: client, cfg: cfg, scratch: scratch, log: log}, nil
}

// EnsureNamespace creates the workload namespace when it is absent.
func (b *Backend) EnsureNamespace(ctx context.Context) error {
	_, err := b.client.CoreV1().Namespaces().Get(ctx, b.cfg.Namespace, metav1.GetOptions{})
	if err == nil {
		return nil
	}
	if !apierrors.IsNotFound(err) {
		return fmt.Errorf("get namespace %s: %w", b.cfg.Namespace, err)
	}
	ns := &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: b.cfg.Namespace, Labels: map[string]string{managedByLabel: managedByValue}}}
	if _, err := b.client.CoreV1().Namespaces().Create(ctx, ns, metav1.CreateOptions{}); err != nil && !apierrors.IsAlreadyExists(err) {
		return fmt.Errorf("create namespace %s: %w", b.cfg.Namespace, err)
	}
	b.log.Info("created namespace", "namespace", b.cfg.Namespace)
	return nil
}

// Create provisions the instance's resources and returns without waiting for
// the pod: the runtime polls Status.
func (b *Backend) Create(ctx context.Context, spec workload.Spec) (workload.Status, error) {
	if spec.InstanceID == "" {
		return workload.Status{}, errors.New("workload spec has no instance id")
	}
	if spec.Port < 1 || spec.Port > 65535 {
		return workload.Status{}, fmt.Errorf("workload port %d is out of range", spec.Port)
	}
	name := sanitizeName(spec.Name)
	existing, err := b.client.CoreV1().ConfigMaps(b.cfg.Namespace).Get(ctx, resourceName(name), metav1.GetOptions{})
	switch {
	case err == nil && existing.Data["instance-id"] == spec.InstanceID:
		complete, gerr := b.graphComplete(ctx, name)
		if gerr != nil {
			return workload.Status{}, gerr
		}
		if complete {
			return b.created(name, spec), nil
		}
		b.log.Warn("mcp resource graph is incomplete, re-creating", "instance_id", spec.InstanceID)
		if cerr := b.cleanup(ctx, name); cerr != nil {
			return workload.Status{}, fmt.Errorf("clean up partial resources for %s: %w", name, cerr)
		}
	case err == nil:
		b.log.Info("stale resources of another instance, cleaning up",
			"instance_name", name, "existing_instance_id", existing.Data["instance-id"], "instance_id", spec.InstanceID)
		if cerr := b.cleanup(ctx, name); cerr != nil {
			return workload.Status{}, fmt.Errorf("clean up stale resources for %s: %w", name, cerr)
		}
	case !apierrors.IsNotFound(err):
		return workload.Status{}, fmt.Errorf("check existing resources of %s: %w", name, err)
	}
	for _, create := range []func(context.Context, string, workload.Spec) error{
		b.createConfigMap, b.createSecret, b.createDeployment, b.createService,
	} {
		if err := create(ctx, name, spec); err != nil {
			if cerr := b.cleanup(ctx, name); cerr != nil {
				b.log.Error("cleanup after a failed create failed", "instance_name", name, "error", cerr)
				return workload.Status{}, fmt.Errorf("create kubernetes resources: %w", errors.Join(err, cerr))
			}
			return workload.Status{}, fmt.Errorf("create kubernetes resources: %w", err)
		}
	}
	b.log.Info("created kubernetes instance", "instance_id", spec.InstanceID, "instance_name", name)
	return b.created(name, spec), nil
}

func (b *Backend) created(name string, spec workload.Spec) workload.Status {
	return workload.Status{
		ID: spec.InstanceID, Name: name, Status: workload.StatusStarting,
		InternalURL: b.internalURL(name), Port: spec.Port,
	}
}

// Delete removes every resource of the instance.
func (b *Backend) Delete(ctx context.Context, instanceID string) error {
	name, err := b.findName(ctx, instanceID)
	if errors.Is(err, workload.ErrNotFound) {
		return nil
	}
	if err != nil {
		return err
	}
	if err := b.cleanup(ctx, name); err != nil {
		return fmt.Errorf("delete instance %s: %w", instanceID, err)
	}
	b.log.Info("deleted kubernetes instance", "instance_id", instanceID, "instance_name", name)
	return nil
}

// Status reports the instance: starting until its pod is ready, stopped when
// its server exited before ever becoming ready, with that output redacted of
// the instance's own secret values.
func (b *Backend) Status(ctx context.Context, instanceID string) (workload.Status, error) {
	name, err := b.findName(ctx, instanceID)
	if err != nil {
		return workload.Status{}, err
	}
	complete, err := b.graphComplete(ctx, name)
	if err != nil {
		return workload.Status{}, err
	}
	if !complete {
		return workload.Status{}, fmt.Errorf("%w: incomplete kubernetes resource graph for %s", workload.ErrNotFound, instanceID)
	}
	rn := resourceName(name)
	deployment, err := b.client.AppsV1().Deployments(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
	if err != nil {
		return workload.Status{}, b.getErr("deployment", instanceID, err)
	}
	cm, err := b.client.CoreV1().ConfigMaps(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
	if err != nil {
		return workload.Status{}, b.getErr("configmap", instanceID, err)
	}
	port, err := strconv.Atoi(cm.Data["port"])
	if err != nil {
		return workload.Status{}, fmt.Errorf("configmap %s carries no usable port %q: %w", rn, cm.Data["port"], err)
	}
	st := workload.Status{
		ID: instanceID, Name: name, Status: deploymentStatus(deployment),
		InternalURL: b.internalURL(name), Port: port, Labels: deployment.Labels,
	}
	if st.Status != workload.StatusStarting {
		return st, nil
	}
	output, crashed, err := b.startupCrash(ctx, deployment)
	if err != nil || !crashed {
		return st, err
	}
	secret, err := b.client.CoreV1().Secrets(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
	if err != nil {
		return workload.Status{}, b.getErr("secret", instanceID, err)
	}
	st.Status, st.Message = workload.StatusStopped, redactSecretValues(output, secret.Data)
	return st, nil
}

func (b *Backend) getErr(kind, instanceID string, err error) error {
	if apierrors.IsNotFound(err) {
		return fmt.Errorf("%w: %s of %s", workload.ErrNotFound, kind, instanceID)
	}
	return fmt.Errorf("get %s of %s: %w", kind, instanceID, err)
}

// Reservation is the default request of each dimension, else its default limit.
func (b *Backend) Reservation(context.Context) (workload.Reservation, error) {
	return reservation(b.cfg.DefaultRequests, b.cfg.DefaultLimits)
}

func reservation(requests, limits Quantities) (workload.Reservation, error) {
	cpu, err := firstQuantity(requests.CPU, limits.CPU)
	if err != nil {
		return workload.Reservation{}, fmt.Errorf("cpu: %w", err)
	}
	memory, err := firstQuantity(requests.Memory, limits.Memory)
	if err != nil {
		return workload.Reservation{}, fmt.Errorf("memory: %w", err)
	}
	return workload.Reservation{CPUMillicores: cpu.MilliValue(), MemoryBytes: memory.Value()}, nil
}

func firstQuantity(values ...string) (resource.Quantity, error) {
	for _, v := range values {
		if v != "" {
			return resource.ParseQuantity(v)
		}
	}
	return resource.Quantity{}, nil
}

func (b *Backend) graphComplete(ctx context.Context, name string) (bool, error) {
	rn := resourceName(name)
	gets := []func() error{
		func() error {
			_, err := b.client.CoreV1().ConfigMaps(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
			return err
		},
		func() error {
			_, err := b.client.CoreV1().Secrets(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
			return err
		},
		func() error {
			_, err := b.client.AppsV1().Deployments(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
			return err
		},
		func() error {
			_, err := b.client.CoreV1().Services(b.cfg.Namespace).Get(ctx, rn, metav1.GetOptions{})
			return err
		},
	}
	for _, get := range gets {
		if err := get(); err != nil {
			if apierrors.IsNotFound(err) {
				return false, nil
			}
			return false, fmt.Errorf("inspect mcp resource graph %s: %w", rn, err)
		}
	}
	return true, nil
}

// findName finds the instance's resource name by the instance id its
// Deployment's pod template or its ConfigMap carries.
func (b *Backend) findName(ctx context.Context, instanceID string) (string, error) {
	selector := labels.SelectorFromSet(labels.Set{managedByLabel: managedByValue}).String()
	deployments, err := b.client.AppsV1().Deployments(b.cfg.Namespace).List(ctx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		return "", fmt.Errorf("list deployments: %w", err)
	}
	for _, d := range deployments.Items {
		if d.Spec.Template.Annotations[instanceIDKey] == instanceID {
			return strings.TrimPrefix(d.Name, "mcp-"), nil
		}
	}
	selector = labels.SelectorFromSet(labels.Set{managedByLabel: managedByValue, componentLabel: componentValue}).String()
	cms, err := b.client.CoreV1().ConfigMaps(b.cfg.Namespace).List(ctx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		return "", fmt.Errorf("list configmaps: %w", err)
	}
	for _, cm := range cms.Items {
		if cm.Data["instance-id"] == instanceID {
			return strings.TrimPrefix(cm.Name, "mcp-"), nil
		}
	}
	return "", fmt.Errorf("%w: %s", workload.ErrNotFound, instanceID)
}

func deploymentStatus(d *appsv1.Deployment) string {
	if d.Status.ReadyReplicas > 0 && d.Status.ReadyReplicas == d.Status.Replicas {
		return workload.StatusRunning
	}
	return workload.StatusStarting
}

// startupCrash reports whether the server container exited before it ever
// became ready, with the output it left. Such a container only crash-loops
// until the startup probe gives up.
func (b *Backend) startupCrash(ctx context.Context, d *appsv1.Deployment) (string, bool, error) {
	if d.Spec.Selector == nil {
		return "", false, nil
	}
	pods, err := b.client.CoreV1().Pods(b.cfg.Namespace).List(ctx, metav1.ListOptions{
		LabelSelector: labels.SelectorFromSet(d.Spec.Selector.MatchLabels).String(),
	})
	if err != nil {
		return "", false, fmt.Errorf("list pods: %w", err)
	}
	for _, pod := range pods.Items {
		// A predecessor's pods linger under the same labels while they go away.
		if pod.DeletionTimestamp != nil || pod.CreationTimestamp.Before(&d.CreationTimestamp) {
			continue
		}
		for _, c := range pod.Status.ContainerStatuses {
			// A run that passed the startup probe has started; lost readiness is not a crash.
			if c.Name != serverContainerName || c.Ready || (c.Started != nil && *c.Started) {
				continue
			}
			if t := c.State.Terminated; t != nil {
				return strings.TrimSpace(t.Message), true, nil
			}
			if t := c.LastTerminationState.Terminated; t != nil && c.RestartCount > 0 {
				return strings.TrimSpace(t.Message), true, nil
			}
		}
	}
	return "", false, nil
}

// minRedactedSecretLength keeps short values such as "1" or "true" from
// blanking out unrelated words.
const minRedactedSecretLength = 6

func redactSecretValues(output string, secrets map[string][]byte) string {
	for _, value := range secrets {
		// A multi-line value, such as a PEM key, is printed a line at a time.
		for _, part := range append([]string{string(value)}, strings.Split(string(value), "\n")...) {
			part = strings.TrimSpace(part)
			if len(part) >= minRedactedSecretLength {
				output = strings.ReplaceAll(output, part, "[REDACTED]")
			}
		}
	}
	return output
}

func (b *Backend) internalURL(name string) string {
	return fmt.Sprintf("http://mcp-%s.%s.svc.cluster.local:80", name, b.cfg.Namespace)
}

func resourceName(name string) string { return "mcp-" + name }

// sanitizeName turns an instance name into a DNS label fragment.
func sanitizeName(name string) string {
	var sb strings.Builder
	for _, r := range strings.NewReplacer("_", "-", " ", "-").Replace(strings.ToLower(name)) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' {
			sb.WriteRune(r)
		}
	}
	s := strings.Trim(sb.String(), "-")
	if s == "" {
		s = "instance"
	}
	if len(s) > 253 {
		s = strings.TrimSuffix(s[:253], "-")
	}
	return s
}

func commonLabels(name string) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":     componentValue,
		"app.kubernetes.io/instance": name,
		componentLabel:               componentValue,
		managedByLabel:               managedByValue,
		"agentarea.io/instance":      name,
	}
}
