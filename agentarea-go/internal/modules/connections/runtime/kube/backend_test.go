package kube

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	k8sruntime "k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

const (
	testNamespace  = "agentarea"
	testInstanceID = "11111111-1111-1111-1111-111111111111"
)

func quietLogger() *slog.Logger { return slog.New(slog.DiscardHandler) }

func testConfig(tier string) Config {
	return Config{
		Namespace:            testNamespace,
		ImagePullPolicy:      string(corev1.PullIfNotPresent),
		DefaultRequests:      Quantities{CPU: "100m", Memory: "256Mi"},
		DefaultLimits:        Quantities{CPU: "500m", Memory: "512Mi"},
		SecurityContext:      SecurityContext{RunAsNonRoot: true, RunAsUser: 1000, ReadOnlyRootFilesystem: true, DropCapabilities: []string{"ALL"}},
		DefaultIsolationTier: tier,
	}
}

func testBackend(t *testing.T, cfg Config, objects ...k8sruntime.Object) (*Backend, *fake.Clientset) {
	t.Helper()
	cs := fake.NewClientset(objects...)
	b, err := NewWithClient(cfg, cs, quietLogger())
	if err != nil {
		t.Fatal(err)
	}
	return b, cs
}

func testSpec() workload.Spec {
	return workload.Spec{InstanceID: testInstanceID, Name: testInstanceID, Image: "ghcr.io/vendor/mcp:1.0", Port: 8080, ServiceName: testInstanceID}
}

func renderDeployment(t *testing.T, tier string) *appsv1.Deployment {
	t.Helper()
	b, _ := testBackend(t, testConfig(tier))
	d, err := b.deployment("instance", testSpec())
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func graphObjects(name string, kinds ...string) []k8sruntime.Object {
	meta := metav1.ObjectMeta{Name: "mcp-" + name, Namespace: testNamespace}
	var out []k8sruntime.Object
	for _, kind := range kinds {
		switch kind {
		case "ConfigMap":
			out = append(out, &corev1.ConfigMap{ObjectMeta: meta})
		case "Secret":
			out = append(out, &corev1.Secret{ObjectMeta: meta})
		case "Deployment":
			out = append(out, &appsv1.Deployment{ObjectMeta: meta})
		case "Service":
			out = append(out, &corev1.Service{ObjectMeta: meta})
		}
	}
	return out
}

// An instance is only present when every resource it needs exists; a graph
// missing its Service or Secret must be repaired, not reported complete.
func TestPartialResourceGraphIsNotTreatedAsPresent(t *testing.T) {
	full := []string{"ConfigMap", "Secret", "Deployment", "Service"}
	for _, missing := range full {
		t.Run("missing "+missing, func(t *testing.T) {
			var present []string
			for _, k := range full {
				if k != missing {
					present = append(present, k)
				}
			}
			b, _ := testBackend(t, testConfig(workload.IsolationStandard), graphObjects("inst", present...)...)
			complete, err := b.graphComplete(context.Background(), "inst")
			if err != nil {
				t.Fatal(err)
			}
			if complete {
				t.Fatalf("a graph missing its %s was reported complete", missing)
			}
		})
	}
}

// An RBAC or API outage is never read as "nothing exists".
func TestUnreadableResourceGraphFailsInsteadOfReportingAbsence(t *testing.T) {
	denied := errors.New("configmaps is forbidden")
	b, cs := testBackend(t, testConfig(workload.IsolationStandard), graphObjects("inst", "ConfigMap", "Secret", "Deployment", "Service")...)
	cs.PrependReactor("get", "*", func(k8stesting.Action) (bool, k8sruntime.Object, error) { return true, nil, denied })
	complete, err := b.graphComplete(context.Background(), "inst")
	if !errors.Is(err, denied) || complete {
		t.Fatalf("complete=%v err=%v, want the API failure", complete, err)
	}
}

func TestCreateIsIdempotentAndReportsStarting(t *testing.T) {
	b, cs := testBackend(t, testConfig(workload.IsolationStandard))
	ctx := context.Background()
	for attempt := range 2 {
		st, err := b.Create(ctx, testSpec())
		if err != nil {
			t.Fatalf("attempt %d: %v", attempt, err)
		}
		if st.Status != workload.StatusStarting || st.InternalURL != "http://mcp-"+testInstanceID+".agentarea.svc.cluster.local:80" {
			t.Fatalf("attempt %d: status %+v", attempt, st)
		}
	}
	cm, err := cs.CoreV1().ConfigMaps(testNamespace).Get(ctx, "mcp-"+testInstanceID, metav1.GetOptions{})
	if err != nil || cm.Data["instance-id"] != testInstanceID || cm.Data["port"] != "8080" {
		t.Fatalf("configmap %+v err %v", cm, err)
	}
	st, err := b.Status(ctx, testInstanceID)
	if err != nil || st.Status != workload.StatusStarting || st.Port != 8080 {
		t.Fatalf("status %+v err %v", st, err)
	}
}

func TestCreateRepairsAnIncompleteGraph(t *testing.T) {
	b, cs := testBackend(t, testConfig(workload.IsolationStandard))
	ctx := context.Background()
	if _, err := b.Create(ctx, testSpec()); err != nil {
		t.Fatal(err)
	}
	if err := cs.CoreV1().Services(testNamespace).Delete(ctx, "mcp-"+testInstanceID, metav1.DeleteOptions{}); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Status(ctx, testInstanceID); !errors.Is(err, workload.ErrNotFound) {
		t.Fatalf("status of an incomplete graph: %v, want ErrNotFound", err)
	}
	if _, err := b.Create(ctx, testSpec()); err != nil {
		t.Fatal(err)
	}
	if _, err := cs.CoreV1().Services(testNamespace).Get(ctx, "mcp-"+testInstanceID, metav1.GetOptions{}); err != nil {
		t.Fatalf("service not re-created: %v", err)
	}
}

func TestDeleteRemovesTheGraphAndForgetsAnAbsentInstance(t *testing.T) {
	b, cs := testBackend(t, testConfig(workload.IsolationStandard))
	ctx := context.Background()
	if _, err := b.Create(ctx, testSpec()); err != nil {
		t.Fatal(err)
	}
	if err := b.Delete(ctx, testInstanceID); err != nil {
		t.Fatal(err)
	}
	if list, _ := cs.AppsV1().Deployments(testNamespace).List(ctx, metav1.ListOptions{}); len(list.Items) != 0 {
		t.Fatalf("deployments left: %d", len(list.Items))
	}
	if _, err := b.Status(ctx, testInstanceID); !errors.Is(err, workload.ErrNotFound) {
		t.Fatalf("status after delete: %v", err)
	}
	if err := b.Delete(ctx, testInstanceID); err != nil {
		t.Fatalf("deleting an absent instance: %v", err)
	}
}

func TestRunningDeploymentIsRunning(t *testing.T) {
	b, cs := testBackend(t, testConfig(workload.IsolationStandard))
	ctx := context.Background()
	if _, err := b.Create(ctx, testSpec()); err != nil {
		t.Fatal(err)
	}
	d, _ := cs.AppsV1().Deployments(testNamespace).Get(ctx, "mcp-"+testInstanceID, metav1.GetOptions{})
	d.Status = appsv1.DeploymentStatus{Replicas: 1, ReadyReplicas: 1}
	if _, err := cs.AppsV1().Deployments(testNamespace).UpdateStatus(ctx, d, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if st, err := b.Status(ctx, testInstanceID); err != nil || st.Status != workload.StatusRunning {
		t.Fatalf("status %+v err %v", st, err)
	}
}

func crashObjects(c corev1.ContainerStatus, secret map[string][]byte, shape ...func(*corev1.Pod)) []k8sruntime.Object {
	labels := map[string]string{"app.kubernetes.io/name": "mcp-server", "app.kubernetes.io/instance": "inst", managedByLabel: managedByValue}
	meta := metav1.ObjectMeta{Name: "mcp-inst", Namespace: testNamespace, Labels: labels}
	dmeta := meta
	dmeta.CreationTimestamp = metav1.NewTime(time.Now().Add(-time.Minute))
	replicas := int32(1)
	d := &appsv1.Deployment{
		ObjectMeta: dmeta,
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"app.kubernetes.io/name": "mcp-server", "app.kubernetes.io/instance": "inst"}},
			Template: corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{Annotations: map[string]string{instanceIDKey: testInstanceID}}},
		},
		Status: appsv1.DeploymentStatus{Replicas: 1},
	}
	c.Name = serverContainerName
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "mcp-inst-abc", Namespace: testNamespace, Labels: labels, CreationTimestamp: metav1.Now()},
		Status:     corev1.PodStatus{ContainerStatuses: []corev1.ContainerStatus{c}},
	}
	for _, s := range shape {
		s(pod)
	}
	return []k8sruntime.Object{d, pod,
		&corev1.ConfigMap{ObjectMeta: meta, Data: map[string]string{"port": "8080"}},
		&corev1.Secret{ObjectMeta: meta, Data: secret},
		&corev1.Service{ObjectMeta: meta},
	}
}

func crashStatus(t *testing.T, c corev1.ContainerStatus, secret map[string][]byte, shape ...func(*corev1.Pod)) workload.Status {
	t.Helper()
	b, _ := testBackend(t, testConfig(workload.IsolationStandard), crashObjects(c, secret, shape...)...)
	st, err := b.Status(context.Background(), testInstanceID)
	if err != nil {
		t.Fatal(err)
	}
	return st
}

// A server that exits before it ever listens crash-loops for as long as the
// startup probe allows; reporting it as starting held every caller for the
// whole startup timeout.
func TestContainerThatCrashedBeforeReadyIsStopped(t *testing.T) {
	for name, c := range map[string]corev1.ContainerStatus{
		"back-off": {
			RestartCount: 1,
			State:        corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}},
			LastTerminationState: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
				ExitCode: 1, Message: "sh: 1: some-server: not found\n",
			}},
		},
		"just exited": {State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{ExitCode: 1, Message: "sh: 1: some-server: not found\n"}}},
	} {
		t.Run(name, func(t *testing.T) {
			st := crashStatus(t, c, nil)
			if st.Status != workload.StatusStopped || st.Message != "sh: 1: some-server: not found" {
				t.Fatalf("status %q message %q", st.Status, st.Message)
			}
		})
	}
}

func TestContainerStillStartingIsNotStopped(t *testing.T) {
	st := crashStatus(t, corev1.ContainerStatus{State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}}}, nil)
	if st.Status != workload.StatusStarting || st.Message != "" {
		t.Fatalf("status %q message %q", st.Status, st.Message)
	}
}

func crashLooping() corev1.ContainerStatus {
	return corev1.ContainerStatus{
		RestartCount: 3,
		State:        corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}},
		LastTerminationState: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
			ExitCode: 1, Message: "the previous workload's output",
		}},
	}
}

// A re-created workload starts while its predecessor's pods still go away
// under the same labels; their crash is not the new start's.
func TestPodsOfAnEarlierWorkloadDoNotStopANewStart(t *testing.T) {
	for name, shape := range map[string]func(*corev1.Pod){
		"being deleted": func(p *corev1.Pod) {
			now := metav1.Now()
			p.DeletionTimestamp = &now
			p.Finalizers = []string{"test/keep"}
		},
		"created before the deployment": func(p *corev1.Pod) {
			p.CreationTimestamp = metav1.NewTime(time.Now().Add(-time.Hour))
		},
	} {
		t.Run(name, func(t *testing.T) {
			if st := crashStatus(t, crashLooping(), nil, shape); st.Status != workload.StatusStarting {
				t.Fatalf("status %q, want starting", st.Status)
			}
		})
	}
}

// Once the current run passed the startup probe, an old restart and a moment
// of lost readiness are not a crash.
func TestAStartedContainerIsNotStoppedForAnOldRestart(t *testing.T) {
	started := true
	st := crashStatus(t, corev1.ContainerStatus{
		RestartCount: 1, Started: &started,
		State: corev1.ContainerState{Running: &corev1.ContainerStateRunning{}},
		LastTerminationState: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
			ExitCode: 137, Message: "killed by liveness probe yesterday",
		}},
	}, nil)
	if st.Status != workload.StatusStarting {
		t.Fatalf("status %q, want starting", st.Status)
	}
}

// The output is the server's stderr; the instance's own secret values never leave.
func TestCrashOutputCarriesNoSecretValue(t *testing.T) {
	st := crashStatus(t, corev1.ContainerStatus{State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
		ExitCode: 1, Message: "auth failed for token tok-0123456789abcdef",
	}}}, map[string][]byte{"API_TOKEN": []byte("tok-0123456789abcdef")})
	if strings.Contains(st.Message, "tok-0123456789abcdef") || !strings.Contains(st.Message, "auth failed for token") {
		t.Fatalf("message %q", st.Message)
	}
}

func TestCrashOutputCarriesNoLineOfAMultiLineSecret(t *testing.T) {
	st := crashStatus(t, corev1.ContainerStatus{State: corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{
		ExitCode: 1, Message: "bad key line: MIIEvQIBADANBgkqhkiG9w0BAQEFAASC",
	}}}, map[string][]byte{"KEY": []byte("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----\n")}) // pragma: allowlist secret
	if strings.Contains(st.Message, "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC") {
		t.Fatalf("message %q leaks a line of the secret", st.Message)
	}
}

func TestDeploymentAsksForTheLogTailOnError(t *testing.T) {
	c := renderDeployment(t, workload.IsolationStandard).Spec.Template.Spec.Containers[0]
	if c.TerminationMessagePolicy != corev1.TerminationMessageFallbackToLogsOnError {
		t.Fatalf("terminationMessagePolicy = %q", c.TerminationMessagePolicy)
	}
}

// The standard tier must not demand a runtime class the cluster may not have.
func TestStandardTierSchedulesOnTheNodeDefaultRuntime(t *testing.T) {
	d := renderDeployment(t, workload.IsolationStandard)
	if rc := d.Spec.Template.Spec.RuntimeClassName; rc != nil {
		t.Fatalf("RuntimeClassName = %q", *rc)
	}
	if len(d.Spec.Template.Spec.Containers[0].SecurityContext.Capabilities.Drop) == 0 {
		t.Fatal("the standard tier dropped no capabilities")
	}
}

func TestUntrustedTierStillDemandsItsRuntime(t *testing.T) {
	rc := renderDeployment(t, workload.IsolationUntrusted).Spec.Template.Spec.RuntimeClassName
	if rc == nil || *rc != workload.UntrustedRuntime {
		t.Fatalf("RuntimeClassName = %v, want %q", rc, workload.UntrustedRuntime)
	}
}

// Every cold call pays the start, so dead time in the probe is dead time in it.
func TestReadinessIsPolledImmediatelyAndOftenOnColdStart(t *testing.T) {
	c := renderDeployment(t, workload.IsolationStandard).Spec.Template.Spec.Containers[0]
	if c.ReadinessProbe.InitialDelaySeconds != 0 || c.ReadinessProbe.PeriodSeconds != 1 {
		t.Fatalf("readiness probe %+v", c.ReadinessProbe)
	}
	if c.StartupProbe == nil || c.StartupProbe.FailureThreshold < 60 {
		t.Fatalf("startup probe %+v", c.StartupProbe)
	}
	if c.LivenessProbe.InitialDelaySeconds == 0 {
		t.Fatal("liveness can kill a container that is still starting")
	}
}

func TestTerminationIsNotLeftAtTheThirtySecondDefault(t *testing.T) {
	grace := renderDeployment(t, workload.IsolationStandard).Spec.Template.Spec.TerminationGracePeriodSeconds
	if grace == nil || *grace > 10 {
		t.Fatalf("TerminationGracePeriodSeconds = %v", grace)
	}
}

func TestEveryScratchVolumeIsBounded(t *testing.T) {
	b, _ := testBackend(t, testConfig(workload.IsolationStandard))
	spec := testSpec()
	spec.WritablePaths = []string{"/data"}
	d, err := b.deployment("instance", spec)
	if err != nil {
		t.Fatal(err)
	}
	vols := d.Spec.Template.Spec.Volumes
	if len(vols) != 3 {
		t.Fatalf("volumes %d, want tmp, var-run and one writable path", len(vols))
	}
	for _, v := range vols {
		if v.EmptyDir == nil || v.EmptyDir.SizeLimit == nil || v.EmptyDir.SizeLimit.IsZero() {
			t.Fatalf("volume %q is unbounded", v.Name)
		}
	}
	if !*d.Spec.Template.Spec.Containers[0].SecurityContext.ReadOnlyRootFilesystem {
		t.Fatal("writable paths did not make the root read-only")
	}
}

func TestPodGetsNoServiceAccountTokenAndStripsStdioTransport(t *testing.T) {
	b, _ := testBackend(t, testConfig(workload.IsolationStandard))
	spec := testSpec()
	spec.Command = []string{"--transport=stdio", "--port", "8080"}
	d, err := b.deployment("instance", spec)
	if err != nil {
		t.Fatal(err)
	}
	pod := d.Spec.Template.Spec
	if pod.AutomountServiceAccountToken == nil || *pod.AutomountServiceAccountToken {
		t.Fatal("instance pods must not mount the service account token")
	}
	if got := strings.Join(pod.Containers[0].Args, " "); got != "--port 8080" {
		t.Fatalf("args %q", got)
	}
	if d.Spec.Template.Annotations[instanceIDKey] != testInstanceID {
		t.Fatalf("annotations %v", d.Spec.Template.Annotations)
	}
}

func deploymentWithLabels(t *testing.T, operator, spec map[string]string) map[string]string {
	t.Helper()
	cfg := testConfig(workload.IsolationStandard)
	cfg.InstancePod.Labels = operator
	b, _ := testBackend(t, cfg)
	s := testSpec()
	s.Labels = spec
	d, err := b.deployment("instance", s)
	if err != nil {
		t.Fatal(err)
	}
	return d.Spec.Template.Labels
}

// The egress label moves a pod out of the default egress policy, so it comes
// from the platform-assembled spec and from nowhere else.
func TestDeploymentCarriesTheSpecEgressLabelOnly(t *testing.T) {
	labels := deploymentWithLabels(t, map[string]string{EgressLabel: "from-operator"}, map[string]string{EgressLabel: "exit-a", "team": "a"})
	if labels[EgressLabel] != "exit-a" {
		t.Fatalf("egress label %q", labels[EgressLabel])
	}
	if _, ok := labels["team"]; ok {
		t.Fatalf("an arbitrary spec label reached the pod: %v", labels)
	}
}

func TestOperatorPodLabelsCannotSetPlatformLabels(t *testing.T) {
	labels := deploymentWithLabels(t, map[string]string{EgressLabel: "x", DataPlaneOwnerLabel: "y", managedByLabel: "z", "team": "ops"}, nil)
	if _, ok := labels[EgressLabel]; ok {
		t.Fatal("operator defaults set the egress label")
	}
	if _, ok := labels[DataPlaneOwnerLabel]; ok {
		t.Fatal("operator defaults set the data plane owner")
	}
	if labels[managedByLabel] != managedByValue || labels["team"] != "ops" {
		t.Fatalf("labels %v", labels)
	}
}

func TestDataPlaneOwnerComesFromTheSpecAndIsReported(t *testing.T) {
	b, _ := testBackend(t, testConfig(workload.IsolationStandard))
	spec := testSpec()
	spec.Labels = map[string]string{DataPlaneOwnerLabel: "dp-1"}
	if _, err := b.Create(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	st, err := b.Status(context.Background(), testInstanceID)
	if err != nil || st.Labels[DataPlaneOwnerLabel] != "dp-1" {
		t.Fatalf("status %+v err %v", st, err)
	}
}

// A requested limit may only lower the operator's ceiling; a missing or
// unreadable ceiling refuses it.
func TestAnUnusableCeilingRefusesTheRequestedLimit(t *testing.T) {
	requested := Quantities{CPU: "64", Memory: "100Gi"}
	for name, allowed := range map[string]Quantities{
		"no ceiling at all": {},
		"malformed memory":  {CPU: "1", Memory: "100 gigabytes"},
		"malformed cpu":     {CPU: "all", Memory: "512Mi"},
		"only cpu declared": {CPU: "1"},
	} {
		if err := ceilingWithin(allowed, requested); err == nil {
			t.Fatalf("%s: an oversized limit was accepted", name)
		}
	}
	allowed := Quantities{CPU: "2", Memory: "1Gi"}
	if err := ceilingWithin(allowed, Quantities{CPU: "1", Memory: "512Mi"}); err != nil {
		t.Fatal(err)
	}
	if err := ceilingWithin(allowed, requested); err == nil || !strings.Contains(err.Error(), "exceeds") {
		t.Fatalf("err %v", err)
	}
}

func TestCreateRefusesAnOversizedOrMalformedLimitAndLeavesNothing(t *testing.T) {
	for name, limits := range map[string]workload.ResourceList{
		"oversized": {CPU: "64"},
		"malformed": {Memory: "lots"},
	} {
		t.Run(name, func(t *testing.T) {
			b, cs := testBackend(t, testConfig(workload.IsolationStandard))
			spec := testSpec()
			spec.Resources.Limits = limits
			if _, err := b.Create(context.Background(), spec); err == nil {
				t.Fatal("create accepted the limit")
			}
			if list, _ := cs.CoreV1().ConfigMaps(testNamespace).List(context.Background(), metav1.ListOptions{}); len(list.Items) != 0 {
				t.Fatal("a refused create left resources behind")
			}
		})
	}
}

func TestReservationIsTheRequestElseTheLimit(t *testing.T) {
	got, err := reservation(Quantities{CPU: "100m"}, Quantities{CPU: "500m", Memory: "512Mi"})
	if err != nil {
		t.Fatal(err)
	}
	if want := (workload.Reservation{CPUMillicores: 100, MemoryBytes: 512 << 20}); got != want {
		t.Fatalf("got %+v, want %+v", got, want)
	}
	if _, err := reservation(Quantities{CPU: "lots"}, Quantities{}); err == nil {
		t.Fatal("an unparsable cpu request was accepted")
	}
}

func TestLoadConfigReadsTheExistingNames(t *testing.T) {
	l := config.FromMap(map[string]string{
		"AGENTAREA_K8S_NAMESPACE":       "mcp",
		"AGENTAREA_K8S_RUNTIME_CLASS":   "gvisor",
		"AGENTAREA_K8S_SERVICE_ACCOUNT": "mcp-runtime",
		"AGENTAREA_K8S_PULL_POLICY":     "always",
		"AGENTAREA_K8S_CPU_LIMIT":       "1",
		"AGENTAREA_K8S_RUN_AS_USER":     "2000",
		"AGENTAREA_K8S_READONLY_ROOT":   "false",
		"AGENTAREA_K8S_INSTANCE_POD":    `{"labels":{"team":"a"},"scratchSizeLimit":"1Gi","imagePullSecrets":["reg"]}`,
		"AGENTAREA_MCP_ISOLATION":       "standard",
		"KUBECONFIG":                    "/etc/exec/kubeconfig",
	})
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if cfg.Namespace != "mcp" || cfg.RuntimeClass != "gvisor" || cfg.PodServiceAccountName != "mcp-runtime" ||
		cfg.ImagePullPolicy != "Always" || cfg.DefaultLimits.CPU != "1" || cfg.DefaultLimits.Memory != "512Mi" ||
		cfg.SecurityContext.RunAsUser != 2000 || cfg.SecurityContext.ReadOnlyRootFilesystem ||
		cfg.InstancePod.Labels["team"] != "a" || cfg.InstancePod.ScratchSizeLimit != "1Gi" ||
		cfg.DefaultIsolationTier != workload.IsolationStandard || cfg.Kubeconfig != "/etc/exec/kubeconfig" {
		t.Fatalf("config %+v", cfg)
	}
}

func TestLoadConfigDefaultsToTheUntrustedTier(t *testing.T) {
	l := config.FromMap(nil)
	cfg := LoadConfig(l)
	if err := l.Err(); err != nil || cfg.DefaultIsolationTier != workload.IsolationUntrusted || cfg.Namespace != "agentarea" {
		t.Fatalf("config %+v err %v", cfg, err)
	}
	q, err := cfg.scratchSizeLimit()
	if err != nil || q.Cmp(resource.MustParse("256Mi")) != 0 {
		t.Fatalf("scratch %v err %v", q, err)
	}
}

// A typo in a deployment value stops the process; it never runs code unconfined
// or unbounded.
func TestLoadConfigRefusesMalformedValues(t *testing.T) {
	for name, env := range map[string]map[string]string{
		"tier":         {"AGENTAREA_MCP_ISOLATION": "nope"},
		"pod json":     {"AGENTAREA_K8S_INSTANCE_POD": "{"},
		"scratch":      {"AGENTAREA_K8S_INSTANCE_POD": `{"scratchSizeLimit":"0"}`},
		"run as user":  {"AGENTAREA_K8S_RUN_AS_USER": "root"},
		"pull policy":  {"AGENTAREA_K8S_PULL_POLICY": "sometimes"},
		"memory limit": {"AGENTAREA_K8S_MEMORY_LIMIT": "lots"},
	} {
		t.Run(name, func(t *testing.T) {
			l := config.FromMap(env)
			LoadConfig(l)
			if l.Err() == nil {
				t.Fatal("a malformed value was accepted")
			}
		})
	}
}

const testKubeconfig = `apiVersion: v1
kind: Config
clusters:
  - name: execution
    cluster:
      server: https://execution.example:6443
contexts:
  - name: execution
    context:
      cluster: execution
      user: manager
current-context: execution
users:
  - name: manager
    user:
      token: test-token
`

func writeKubeconfig(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "kubeconfig")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// A configured kubeconfig names the cluster workloads run in; it is used, not consulted.
func TestConfiguredKubeconfigIsUsed(t *testing.T) {
	cfg, err := clusterConfig(writeKubeconfig(t, testKubeconfig), quietLogger())
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Host != "https://execution.example:6443" {
		t.Fatalf("targeting %q", cfg.Host)
	}
}

// A broken configured kubeconfig aborts instead of falling through to this
// process's own cluster.
func TestBrokenKubeconfigIsFatalRatherThanIgnored(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "does-not-exist")
	_, err := clusterConfig(missing, quietLogger())
	if err == nil || !strings.Contains(err.Error(), missing) || !strings.Contains(err.Error(), "refusing to fall back") {
		t.Fatalf("err %v", err)
	}
	if _, err := clusterConfig(writeKubeconfig(t, "this is not: [valid yaml\n"), quietLogger()); err == nil {
		t.Fatal("a malformed kubeconfig was accepted")
	}
}

func TestEnsureNamespaceCreatesAnAbsentOne(t *testing.T) {
	b, cs := testBackend(t, testConfig(workload.IsolationStandard))
	for range 2 {
		if err := b.EnsureNamespace(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := cs.CoreV1().Namespaces().Get(context.Background(), testNamespace, metav1.GetOptions{}); err != nil {
		t.Fatal(err)
	}
}
