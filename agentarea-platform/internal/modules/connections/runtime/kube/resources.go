package kube

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"strconv"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

func (b *Backend) meta(name string) metav1.ObjectMeta {
	return metav1.ObjectMeta{Name: resourceName(name), Namespace: b.cfg.Namespace, Labels: commonLabels(name)}
}

func (b *Backend) createConfigMap(ctx context.Context, name string, spec workload.Spec) error {
	cm := &corev1.ConfigMap{
		ObjectMeta: b.meta(name),
		Data: map[string]string{
			"instance-id":  spec.InstanceID,
			"service-name": spec.ServiceName,
			"port":         strconv.Itoa(spec.Port),
			"workspace-id": spec.WorkspaceID,
		},
	}
	if _, err := b.client.CoreV1().ConfigMaps(b.cfg.Namespace).Create(ctx, cm, metav1.CreateOptions{}); err != nil {
		return fmt.Errorf("create configmap: %w", err)
	}
	return nil
}

func (b *Backend) createSecret(ctx context.Context, name string, spec workload.Spec) error {
	data := make(map[string][]byte, len(spec.Environment)+3)
	for k, v := range spec.Environment {
		data[k] = []byte(v)
	}
	data["MCP_INSTANCE_ID"] = []byte(spec.InstanceID)
	data["MCP_SERVICE_NAME"] = []byte(spec.ServiceName)
	data["MCP_CONTAINER_PORT"] = []byte(strconv.Itoa(spec.Port))
	secret := &corev1.Secret{ObjectMeta: b.meta(name), Type: corev1.SecretTypeOpaque, Data: data}
	if _, err := b.client.CoreV1().Secrets(b.cfg.Namespace).Create(ctx, secret, metav1.CreateOptions{}); err != nil {
		return fmt.Errorf("create secret: %w", err)
	}
	return nil
}

// applyQuantities parses spec-supplied quantities; a malformed one is an
// error, never a panic that takes the process down for every tenant.
func applyQuantities(into corev1.ResourceList, q Quantities) error {
	for n, v := range map[corev1.ResourceName]string{corev1.ResourceCPU: q.CPU, corev1.ResourceMemory: q.Memory} {
		if v == "" {
			continue
		}
		parsed, err := resource.ParseQuantity(v)
		if err != nil {
			return fmt.Errorf("%s %q is not a valid quantity: %w", n, v, err)
		}
		if parsed.Sign() <= 0 {
			return fmt.Errorf("%s %q must be positive", n, v)
		}
		into[n] = parsed
	}
	return nil
}

// ceilingWithin refuses a limit above what the operator allows. A missing or
// unusable ceiling refuses too: the requested limit is caller input.
func ceilingWithin(allowed, requested Quantities) error {
	for n, pair := range map[corev1.ResourceName][2]string{
		corev1.ResourceCPU:    {requested.CPU, allowed.CPU},
		corev1.ResourceMemory: {requested.Memory, allowed.Memory},
	} {
		want, ceiling := pair[0], pair[1]
		if want == "" {
			continue
		}
		wq, err := resource.ParseQuantity(want)
		if err != nil {
			return fmt.Errorf("%s %q is not a valid quantity: %w", n, want, err)
		}
		if ceiling == "" {
			return fmt.Errorf("no %s ceiling is configured, refusing the requested %s", n, want)
		}
		cq, err := resource.ParseQuantity(ceiling)
		if err != nil {
			return fmt.Errorf("configured %s ceiling %q is unusable, refusing the requested %s: %w", n, ceiling, want, err)
		}
		if wq.Cmp(cq) > 0 {
			return fmt.Errorf("requested %s %s exceeds the %s this deployment allows", n, want, ceiling)
		}
	}
	return nil
}

func (b *Backend) podLabels(name string, spec workload.Spec) map[string]string {
	out := maps.Clone(b.cfg.InstancePod.Labels)
	if out == nil {
		out = map[string]string{}
	}
	maps.Copy(out, commonLabels(name))
	for _, platform := range []string{DataPlaneOwnerLabel, EgressLabel} {
		delete(out, platform)
		if v := spec.Labels[platform]; v != "" {
			out[platform] = v
		}
	}
	return out
}

func (b *Backend) createDeployment(ctx context.Context, name string, spec workload.Spec) error {
	d, err := b.deployment(name, spec)
	if err != nil {
		return err
	}
	if _, err := b.client.AppsV1().Deployments(b.cfg.Namespace).Create(ctx, d, metav1.CreateOptions{}); err != nil {
		return fmt.Errorf("create deployment: %w", err)
	}
	return nil
}

func (b *Backend) deployment(name string, spec workload.Spec) (*appsv1.Deployment, error) {
	labels := b.podLabels(name, spec)
	limits := b.cfg.limits(spec.Resources.Limits)
	res := corev1.ResourceRequirements{Requests: corev1.ResourceList{}, Limits: corev1.ResourceList{}}
	if err := applyQuantities(res.Requests, b.cfg.requests(spec.Resources.Requests)); err != nil {
		return nil, fmt.Errorf("resource requests: %w", err)
	}
	if err := applyQuantities(res.Limits, limits); err != nil {
		return nil, fmt.Errorf("resource limits: %w", err)
	}
	if err := ceilingWithin(b.cfg.DefaultLimits, limits); err != nil {
		return nil, err
	}
	iso, err := workload.SpecIsolation(spec, b.cfg.DefaultIsolationTier)
	if err != nil {
		return nil, err
	}
	sc := b.cfg.SecurityContext
	readOnlyRoot := sc.ReadOnlyRootFilesystem || iso.ReadOnlyRootFilesystem
	escalation := sc.AllowPrivilegeEscalation && !iso.NoNewPrivileges
	runAsNonRoot, runAsUser := sc.RunAsNonRoot, sc.RunAsUser
	drops := make([]corev1.Capability, 0, len(sc.DropCapabilities)+1)
	for _, c := range workload.TightenDropCapabilities(sc.DropCapabilities, iso) {
		drops = append(drops, corev1.Capability(c))
	}
	tcp := corev1.ProbeHandler{TCPSocket: &corev1.TCPSocketAction{Port: intstr.FromInt(spec.Port)}}
	container := corev1.Container{
		Name:            serverContainerName,
		Image:           spec.Image,
		ImagePullPolicy: corev1.PullPolicy(b.cfg.ImagePullPolicy),
		Ports:           []corev1.ContainerPort{{Name: "http", ContainerPort: int32(spec.Port), Protocol: corev1.ProtocolTCP}}, //nolint:gosec // port is checked to be 1..65535
		EnvFrom: []corev1.EnvFromSource{
			{SecretRef: &corev1.SecretEnvSource{LocalObjectReference: corev1.LocalObjectReference{Name: resourceName(name)}}},
			{ConfigMapRef: &corev1.ConfigMapEnvSource{LocalObjectReference: corev1.LocalObjectReference{Name: resourceName(name)}}},
		},
		Resources: res,
		SecurityContext: &corev1.SecurityContext{
			RunAsNonRoot:             &runAsNonRoot,
			RunAsUser:                &runAsUser,
			ReadOnlyRootFilesystem:   &readOnlyRoot,
			AllowPrivilegeEscalation: &escalation,
			Capabilities:             &corev1.Capabilities{Drop: drops},
		},
		// A server that exits on error leaves its last log lines as the
		// termination message, which Status reports.
		TerminationMessagePolicy: corev1.TerminationMessageFallbackToLogsOnError,
		// TCP probes: an HTTP health path is not part of MCP.
		LivenessProbe: &corev1.Probe{ProbeHandler: tcp, InitialDelaySeconds: 30, PeriodSeconds: 10, TimeoutSeconds: 5, FailureThreshold: 3},
		// Every cold call pays the start, so readiness polls at once and each
		// second; a slow start spends the startup probe's budget instead.
		StartupProbe:   &corev1.Probe{ProbeHandler: tcp, PeriodSeconds: 1, TimeoutSeconds: 2, FailureThreshold: 300},
		ReadinessProbe: &corev1.Probe{ProbeHandler: tcp, PeriodSeconds: 1, TimeoutSeconds: 2, FailureThreshold: 5},
	}
	if len(spec.Entrypoint) > 0 {
		container.Command = spec.Entrypoint
	}
	args := make([]string, 0, len(spec.Command))
	for _, a := range spec.Command {
		// The pod binds its port directly; a stdio transport flag would keep it from listening.
		if a != "--transport=stdio" {
			args = append(args, a)
		}
	}
	if len(args) > 0 {
		container.Args = args
	}
	volumes, mounts := b.scratchVolumes(spec.WritablePaths)
	container.VolumeMounts = mounts

	nonRoot, user, never, grace := runAsNonRoot, runAsUser, false, int64(5)
	pod := corev1.PodSpec{
		SecurityContext: &corev1.PodSecurityContext{
			RunAsNonRoot:   &nonRoot,
			RunAsUser:      &user,
			SeccompProfile: &corev1.SeccompProfile{Type: corev1.SeccompProfileTypeRuntimeDefault},
		},
		Containers: []corev1.Container{container},
		Volumes:    volumes,
		// MCP servers never call the API server; withholding the token keeps a
		// hostile image from reaching the control plane with it.
		AutomountServiceAccountToken: &never,
		// The server's output reaches its owner, so its environment must not
		// list the cluster's other services.
		EnableServiceLinks: &never,
		// The workload holds no state to flush; a long grace only holds the name.
		TerminationGracePeriodSeconds: &grace,
		ServiceAccountName:            b.cfg.PodServiceAccountName,
	}
	if rc := workload.TightenRuntimeClass(b.cfg.RuntimeClass, iso, spec.RuntimeClass); rc != "" {
		pod.RuntimeClassName = &rc
	}
	ip := b.cfg.InstancePod
	pod.NodeSelector, pod.Tolerations, pod.Affinity, pod.PriorityClassName = ip.NodeSelector, ip.Tolerations, ip.Affinity, ip.PriorityClassName
	for _, s := range ip.ImagePullSecrets {
		pod.ImagePullSecrets = append(pod.ImagePullSecrets, corev1.LocalObjectReference{Name: s})
	}
	annotations := maps.Clone(ip.Annotations)
	if annotations == nil {
		annotations = map[string]string{}
	}
	annotations[instanceIDKey] = spec.InstanceID
	annotations[workspaceIDKey] = spec.WorkspaceID
	replicas := int32(1)
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: resourceName(name), Namespace: b.cfg.Namespace, Labels: labels},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: map[string]string{
				"app.kubernetes.io/name": componentValue, "app.kubernetes.io/instance": name,
			}},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels, Annotations: annotations},
				Spec:       pod,
			},
		},
	}, nil
}

// scratchVolumes bounds every emptyDir: nothing survives a restart, so an
// unbounded one only lets an image exhaust the node's ephemeral storage.
func (b *Backend) scratchVolumes(writable []string) ([]corev1.Volume, []corev1.VolumeMount) {
	paths := append([]string{"/tmp", "/var/run"}, writable...)
	names := append([]string{"tmp", "var-run"}, make([]string, len(writable))...)
	for i := range writable {
		names[2+i] = fmt.Sprintf("writable-%d", i)
	}
	volumes := make([]corev1.Volume, 0, len(paths))
	mounts := make([]corev1.VolumeMount, 0, len(paths))
	for i, p := range paths {
		limit := b.scratch.DeepCopy()
		volumes = append(volumes, corev1.Volume{Name: names[i], VolumeSource: corev1.VolumeSource{EmptyDir: &corev1.EmptyDirVolumeSource{SizeLimit: &limit}}})
		mounts = append(mounts, corev1.VolumeMount{Name: names[i], MountPath: p})
	}
	return volumes, mounts
}

func (b *Backend) createService(ctx context.Context, name string, spec workload.Spec) error {
	svc := &corev1.Service{
		ObjectMeta: b.meta(name),
		Spec: corev1.ServiceSpec{
			Selector: map[string]string{"app.kubernetes.io/name": componentValue, "app.kubernetes.io/instance": name},
			Ports:    []corev1.ServicePort{{Name: "http", Port: 80, TargetPort: intstr.FromInt(spec.Port), Protocol: corev1.ProtocolTCP}},
			Type:     corev1.ServiceTypeClusterIP,
		},
	}
	if _, err := b.client.CoreV1().Services(b.cfg.Namespace).Create(ctx, svc, metav1.CreateOptions{}); err != nil {
		return fmt.Errorf("create service: %w", err)
	}
	return nil
}

// cleanup deletes the instance's resources, last created first.
func (b *Backend) cleanup(ctx context.Context, name string) error {
	rn := resourceName(name)
	background := metav1.DeletePropagationBackground
	opts := metav1.DeleteOptions{PropagationPolicy: &background}
	ns := b.cfg.Namespace
	deletes := []struct {
		kind string
		del  func() error
	}{
		{"service", func() error { return b.client.CoreV1().Services(ns).Delete(ctx, rn, opts) }},
		{"deployment", func() error { return b.client.AppsV1().Deployments(ns).Delete(ctx, rn, opts) }},
		{"secret", func() error { return b.client.CoreV1().Secrets(ns).Delete(ctx, rn, opts) }},
		{"configmap", func() error { return b.client.CoreV1().ConfigMaps(ns).Delete(ctx, rn, opts) }},
	}
	var errs []error
	for _, d := range deletes {
		if err := d.del(); err != nil && !apierrors.IsNotFound(err) {
			b.log.Warn("failed to delete resource", "kind", d.kind, "name", rn, "error", err)
			errs = append(errs, fmt.Errorf("delete %s %s: %w", d.kind, rn, err))
		}
	}
	return errors.Join(errs...)
}
