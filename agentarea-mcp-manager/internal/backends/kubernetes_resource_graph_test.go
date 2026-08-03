package backends

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"

	"github.com/agentarea/mcp-manager/internal/config"
)

const graphTestNamespace = "agentarea"

func graphScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	scheme := runtime.NewScheme()
	if err := corev1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	if err := appsv1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	return scheme
}

func graphBackend(t *testing.T, kube client.Client) *KubernetesBackend {
	t.Helper()
	return &KubernetesBackend{
		client:    kube,
		k8sConfig: &config.KubernetesConfig{Namespace: graphTestNamespace},
		logger:    slog.New(slog.NewTextHandler(os.Stdout, nil)),
	}
}

func graphObjects(instanceName string, kinds ...string) []client.Object {
	meta := metav1.ObjectMeta{Name: "mcp-" + instanceName, Namespace: graphTestNamespace}
	objects := make([]client.Object, 0, len(kinds))
	for _, kind := range kinds {
		switch kind {
		case "ConfigMap":
			objects = append(objects, &corev1.ConfigMap{ObjectMeta: meta})
		case "Secret":
			objects = append(objects, &corev1.Secret{ObjectMeta: meta})
		case "Deployment":
			objects = append(objects, &appsv1.Deployment{ObjectMeta: meta})
		case "Service":
			objects = append(objects, &corev1.Service{ObjectMeta: meta})
		}
	}
	return objects
}

// TestPartialResourceGraphIsNotTreatedAsPresent pins the reconcile contract: an
// instance is only "already created" when every resource it needs exists. The
// original check looked at the ConfigMap and Deployment alone, so an instance
// whose Service or Secret had been deleted was reported as complete and was
// never repaired — the workload stayed unreachable, or started without its
// credentials, for as long as the row survived.
func TestPartialResourceGraphIsNotTreatedAsPresent(t *testing.T) {
	full := []string{"ConfigMap", "Secret", "Deployment", "Service"}
	for _, missing := range full {
		t.Run("missing "+missing, func(t *testing.T) {
			present := make([]string, 0, len(full)-1)
			for _, kind := range full {
				if kind != missing {
					present = append(present, kind)
				}
			}
			kube := fake.NewClientBuilder().
				WithScheme(graphScheme(t)).
				WithObjects(graphObjects("inst", present...)...).
				Build()

			complete, err := graphBackend(t, kube).instanceResourceGraphComplete(context.Background(), "inst")
			if err != nil {
				t.Fatalf("instanceResourceGraphComplete() error = %v", err)
			}
			if complete {
				t.Fatalf("a graph missing its %s was reported complete; it would never be repaired", missing)
			}
		})
	}
}

func TestCompleteResourceGraphIsAnIdempotentNoOp(t *testing.T) {
	kube := fake.NewClientBuilder().
		WithScheme(graphScheme(t)).
		WithObjects(graphObjects("inst", "ConfigMap", "Secret", "Deployment", "Service")...).
		Build()

	backend := graphBackend(t, kube)
	for attempt := range 3 {
		complete, err := backend.instanceResourceGraphComplete(context.Background(), "inst")
		if err != nil || !complete {
			t.Fatalf("attempt %d: complete=%v err=%v, want a stable no-op", attempt, complete, err)
		}
	}
}

// TestUnreadableResourceGraphFailsInsteadOfReportingAbsence keeps an RBAC or
// API outage from being read as "nothing exists" — the mistake that turns an
// inspection failure into a duplicate workload.
func TestUnreadableResourceGraphFailsInsteadOfReportingAbsence(t *testing.T) {
	denied := errors.New("configmaps is forbidden: user cannot get resource")
	kube := fake.NewClientBuilder().
		WithScheme(graphScheme(t)).
		WithObjects(graphObjects("inst", "ConfigMap", "Secret", "Deployment", "Service")...).
		WithInterceptorFuncs(interceptor.Funcs{
			Get: func(_ context.Context, _ client.WithWatch, _ types.NamespacedName, _ client.Object, _ ...client.GetOption) error {
				return denied
			},
		}).
		Build()

	complete, err := graphBackend(t, kube).instanceResourceGraphComplete(context.Background(), "inst")
	if err == nil {
		t.Fatal("an unreadable resource graph was reported as a definite answer")
	}
	if complete {
		t.Fatal("an unreadable resource graph was reported complete")
	}
	if !errors.Is(err, denied) {
		t.Fatalf("error = %v, want the underlying API failure preserved", err)
	}
}
