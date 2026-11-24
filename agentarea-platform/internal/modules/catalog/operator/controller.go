package operator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/util/workqueue"
)

// Resync is how often every resource is seen again: the hourly rediscovery and token resync.
const Resync = time.Hour

// The watched kinds (agentarea.io/v1alpha1).
const (
	KindProvider   = "llmproviderconfigs"
	KindConnection = "platformconnections"
	KindEgressExit = "platformegressexits"
)

func resource(kind string) schema.GroupVersionResource {
	return schema.GroupVersionResource{Group: "agentarea.io", Version: "v1alpha1", Resource: kind}
}

type item struct {
	kind, namespace, name string
	periodic              bool
}

// Controller watches the declared resources in its own namespace and reconciles each change.
// Two releases sharing a cluster each reconcile only their own declarations.
type Controller struct {
	r       *Reconciler
	dyn     dynamic.Interface
	factory dynamicinformer.DynamicSharedInformerFactory
	queue   workqueue.TypedDelayingInterface[item]
	log     *slog.Logger
}

// ClusterConfig is the in-cluster service account and the pod's namespace, else the ambient
// kubeconfig (KUBECONFIG) and its context's namespace.
func ClusterConfig() (*rest.Config, string, error) {
	kc := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(
		clientcmd.NewDefaultClientConfigLoadingRules(), &clientcmd.ConfigOverrides{})
	cfg, err := kc.ClientConfig()
	if err != nil {
		return nil, "", fmt.Errorf("no cluster to watch: not in a cluster and no kubeconfig: %w", err)
	}
	ns, _, err := kc.Namespace()
	if err != nil {
		return nil, "", fmt.Errorf("the namespace to watch: %w", err)
	}
	return cfg, ns, nil
}

// Secrets reads Kubernetes Secrets through the core API.
type Secrets struct{ c kubernetes.Interface }

// NewSecrets builds the Secret reader over cfg.
func NewSecrets(cfg *rest.Config) (Secrets, error) {
	c, err := kubernetes.NewForConfig(cfg)
	return Secrets{c: c}, err
}

// Read implements SecretReader.
func (s Secrets) Read(ctx context.Context, namespace, name, key string) (string, error) {
	sec, err := s.c.CoreV1().Secrets(namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return "", err
	}
	if v, ok := sec.Data[key]; ok {
		return string(v), nil
	}
	if v, ok := sec.StringData[key]; ok && sec.Type != corev1.SecretTypeServiceAccountToken {
		return v, nil
	}
	return "", fmt.Errorf("Key '%s' not found in Secret '%s'", key, name) //nolint:staticcheck // the status text operators read
}

// NewController builds the controller over cfg, watching namespace.
func NewController(cfg *rest.Config, namespace string, r *Reconciler, log *slog.Logger) (*Controller, error) {
	dyn, err := dynamic.NewForConfig(cfg)
	if err != nil {
		return nil, err
	}
	return newController(dyn, namespace, r, log), nil
}

func newController(dyn dynamic.Interface, namespace string, r *Reconciler, log *slog.Logger) *Controller {
	return &Controller{r: r, dyn: dyn, factory: dynamicinformer.NewFilteredDynamicSharedInformerFactory(dyn, Resync, namespace, nil),
		queue: workqueue.NewTypedDelayingQueue[item](), log: log}
}

// Name implements lifecycle.Component.
func (*Controller) Name() string { return "operator" }

// Run watches until ctx ends. A resource is reconciled when first seen and whenever its spec
// changes; the hourly resync runs the periodic handlers.
func (c *Controller) Run(ctx context.Context) error {
	for _, kind := range []string{KindProvider, KindConnection, KindEgressExit} {
		informer := c.factory.ForResource(resource(kind)).Informer()
		if _, err := informer.AddEventHandler(cache.ResourceEventHandlerFuncs{
			AddFunc: func(obj any) { c.enqueue(kind, obj, false) },
			UpdateFunc: func(old, cur any) {
				o, ok1 := old.(*unstructured.Unstructured)
				n, ok2 := cur.(*unstructured.Unstructured)
				switch {
				case !ok1 || !ok2:
				case o.GetResourceVersion() == n.GetResourceVersion():
					c.enqueue(kind, cur, true)
				case o.GetGeneration() != n.GetGeneration():
					c.enqueue(kind, cur, false)
				}
			},
		}); err != nil {
			return err
		}
	}
	c.factory.Start(ctx.Done())
	for gvr, synced := range c.factory.WaitForCacheSync(ctx.Done()) {
		if !synced && ctx.Err() == nil {
			return fmt.Errorf("the %s watch did not sync", gvr.Resource)
		}
	}
	go func() {
		<-ctx.Done()
		c.queue.ShutDown()
	}()
	for {
		it, shutdown := c.queue.Get()
		if shutdown {
			c.factory.Shutdown()
			return nil
		}
		c.process(ctx, it)
		c.queue.Done(it)
	}
}

func (c *Controller) enqueue(kind string, obj any, periodic bool) {
	u, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return
	}
	c.queue.Add(item{kind: kind, namespace: u.GetNamespace(), name: u.GetName(), periodic: periodic})
}

func (c *Controller) process(ctx context.Context, it item) {
	obj, exists, err := c.factory.ForResource(resource(it.kind)).Informer().GetIndexer().GetByKey(it.namespace + "/" + it.name)
	if err != nil || !exists {
		return
	}
	u, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return
	}
	spec, _, _ := unstructured.NestedMap(u.Object, "spec")
	if spec == nil {
		spec = map[string]any{}
	}
	var out *Outcome
	switch {
	case it.kind == KindProvider && it.periodic:
		out = c.r.Rediscover(ctx, it.namespace, it.name, spec)
	case it.kind == KindProvider:
		c.log.InfoContext(ctx, "Syncing LLMProviderConfig", "resource", it.namespace+"/"+it.name)
		o := c.r.Provider(ctx, it.namespace, it.name, spec)
		out = &o
	case it.kind == KindConnection && it.periodic:
		out = c.r.Resync(ctx, it.namespace, it.name, spec)
	case it.kind == KindConnection:
		c.log.InfoContext(ctx, "Syncing PlatformConnection", "resource", it.namespace+"/"+it.name, "transport", spec["transport"])
		o := c.r.Connection(ctx, it.namespace, it.name, spec)
		out = &o
	case it.kind == KindEgressExit && !it.periodic:
		c.log.InfoContext(ctx, "Syncing PlatformEgressExit", "resource", it.namespace+"/"+it.name, "via", spec["via"])
		o := c.r.EgressExit(ctx, it.namespace, it.name, spec)
		out = &o
	}
	if out == nil {
		return
	}
	if err := c.patchStatus(ctx, it, out.Status); err != nil && ctx.Err() == nil {
		c.log.ErrorContext(ctx, "Could not record the status", "resource", it.kind+" "+it.namespace+"/"+it.name, "error", err.Error())
	}
	if out.Retry > 0 && !it.periodic {
		c.log.WarnContext(ctx, "Reconcile will be retried", "resource", it.kind+" "+it.namespace+"/"+it.name,
			"after", out.Retry.String(), "reason", out.Status["message"])
		c.queue.AddAfter(it, out.Retry)
	}
}

func (c *Controller) patchStatus(ctx context.Context, it item, status map[string]any) error {
	body, err := json.Marshal(map[string]any{"status": status})
	if err != nil {
		return err
	}
	_, err = c.dyn.Resource(resource(it.kind)).Namespace(it.namespace).Patch(ctx, it.name, types.MergePatchType, body, metav1.PatchOptions{}, "status")
	return err
}
