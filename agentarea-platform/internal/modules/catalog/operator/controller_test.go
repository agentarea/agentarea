package operator

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	dynamicfake "k8s.io/client-go/dynamic/fake"
)

func declared(kind, namespace, name string) *unstructured.Unstructured {
	u := &unstructured.Unstructured{}
	u.SetGroupVersionKind(schema.GroupVersionKind{Group: "agentarea.io", Version: "v1alpha1", Kind: kind})
	u.SetNamespace(namespace)
	u.SetName(name)
	return u
}

func TestTheControllerWatchesOnlyItsOwnNamespace(t *testing.T) {
	dyn := dynamicfake.NewSimpleDynamicClientWithCustomListKinds(runtime.NewScheme(), map[schema.GroupVersionResource]string{
		resource(KindProvider):   "LLMProviderConfigList",
		resource(KindConnection): "PlatformConnectionList",
		resource(KindEgressExit): "PlatformEgressExitList",
	},
		declared("PlatformEgressExit", "agentarea", "own"),
		declared("PlatformEgressExit", "agentarea-staging", "neighbour"),
	)
	c := newController(dyn, "agentarea", nil, slog.New(slog.DiscardHandler))
	informer := c.factory.ForResource(resource(KindEgressExit)).Informer()
	ctx, cancel := context.WithCancel(context.Background())
	defer func() { cancel(); c.factory.Shutdown() }()
	c.factory.Start(ctx.Done())
	for gvr, ok := range c.factory.WaitForCacheSync(ctx.Done()) {
		if !ok {
			t.Fatalf("%s did not sync", gvr.Resource)
		}
	}
	if got := informer.GetIndexer().ListKeys(); !slices.Equal(got, []string{"agentarea/own"}) {
		t.Fatalf("watched %v, want only agentarea/own", got)
	}
}

func TestTheNamespaceComesFromTheKubeconfigContext(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kubeconfig")
	if err := os.WriteFile(path, []byte(`apiVersion: v1
kind: Config
clusters: [{name: c, cluster: {server: "https://127.0.0.1:6443"}}]
users: [{name: u, user: {token: t}}]
contexts: [{name: x, context: {cluster: c, user: u, namespace: agentarea}}]
current-context: x
`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("KUBECONFIG", path)
	t.Setenv("KUBERNETES_SERVICE_HOST", "")
	_, ns, err := ClusterConfig()
	if err != nil || ns != "agentarea" {
		t.Fatalf("namespace %q, err %v", ns, err)
	}
}
