package builtin

import (
	"fmt"
	"log/slog"

	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// Cluster is the client of the cluster the warm pool runs in.
type Cluster = kubernetes.Interface

// Clientset reaches the cluster the warm pool runs in. A configured kubeconfig
// wins and failing to load it is fatal; empty means this process's cluster,
// else the ambient kubeconfig.
func Clientset(kubeconfig string, log *slog.Logger) (Cluster, error) {
	cfg, err := clusterConfig(kubeconfig, log)
	if err != nil {
		return nil, err
	}
	cs, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		return nil, fmt.Errorf("sandbox kubernetes clientset: %w", err)
	}
	return cs, nil
}

func clusterConfig(kubeconfig string, log *slog.Logger) (*rest.Config, error) {
	if kubeconfig != "" {
		cfg, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
		if err != nil {
			return nil, fmt.Errorf("loading the configured sandbox cluster kubeconfig %q: %w", kubeconfig, err)
		}
		log.Info("sandbox uses the configured cluster", "kubeconfig", kubeconfig, "host", cfg.Host)
		return cfg, nil
	}
	cfg, inClusterErr := rest.InClusterConfig()
	if inClusterErr == nil {
		return cfg, nil
	}
	cfg, err := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(
		clientcmd.NewDefaultClientConfigLoadingRules(), &clientcmd.ConfigOverrides{}).ClientConfig()
	if err != nil {
		return nil, fmt.Errorf("no sandbox cluster available: not in a cluster (%w) and no ambient kubeconfig (%w)", inClusterErr, err)
	}
	return cfg, nil
}
