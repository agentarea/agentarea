package app

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
)

type podObserver struct{ seen []ext.TaskPod }

func (o *podObserver) Allocation(_ context.Context, p ext.TaskPod) error {
	o.seen = append(o.seen, p)
	return nil
}
func (o *podObserver) Lease(context.Context, ext.TaskPod) error                   { return nil }
func (o *podObserver) BeforeDelete(context.Context, ext.TaskPodDelete) error      { return nil }
func (o *podObserver) AfterDelete(context.Context, ext.TaskPodDeleteResult) error { return nil }

type observedRuntime struct {
	sandboxruntime.ManagedRuntime
	pods warmpool.LifecycleObserver
}

func (r *observedRuntime) SetTaskLifecycleObserver(o warmpool.LifecycleObserver) { r.pods = o }

func TestTaskPodsReachTheOverlayAsTheirQuantities(t *testing.T) {
	o := &podObserver{}
	hooks := sandboxHooks([]ext.WorkloadHooks{{TaskPods: o}}, true)
	rt := &observedRuntime{}
	if err := hooks[0](rt, "kubernetes"); err != nil || rt.pods == nil {
		t.Fatalf("observer not attached: %v", err)
	}
	err := rt.pods.Allocation(context.Background(), warmpool.TaskPodSnapshot{UID: "u", Containers: []warmpool.ContainerAllocation{{
		Name: "executor", Resources: corev1.ResourceRequirements{Limits: corev1.ResourceList{corev1.ResourceCPU: resource.MustParse("500m")}}}}})
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(o.seen[0].Containers[0].Resources)
	if string(raw) != `{"limits":{"cpu":"500m"}}` || o.seen[0].Overhead != nil {
		t.Fatalf("resources %s overhead %v", raw, o.seen[0].Overhead)
	}
}

func TestASandboxProcessRefusesARuntimeItCannotObserve(t *testing.T) {
	hooks := sandboxHooks([]ext.WorkloadHooks{{TaskPods: &podObserver{}}}, true)
	if err := hooks[0](struct{ sandboxruntime.ManagedRuntime }{}, "e2b"); err == nil || !strings.Contains(err.Error(), "e2b") {
		t.Fatalf("an unobservable runtime = %v", err)
	}
	if err := sandboxHooks([]ext.WorkloadHooks{{TaskPods: &podObserver{}}}, false)[0](struct{ sandboxruntime.ManagedRuntime }{}, "e2b"); err != nil {
		t.Fatalf("the mcp role refused it: %v", err)
	}
	if sandboxHooks([]ext.WorkloadHooks{{}}, true) != nil {
		t.Fatal("hooks without observers attached something")
	}
}
