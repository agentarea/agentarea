package kube

import (
	"fmt"
	"log/slog"

	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// clusterConfig picks the execution cluster. A configured kubeconfig wins over
// in-cluster credentials and failing to load it is fatal: falling back would
// put untrusted workloads next to the control plane. An empty setting means
// whatever cluster this process is in, else the ambient kubeconfig.
func clusterConfig(kubeconfig string, log *slog.Logger) (*rest.Config, error) {
	if kubeconfig != "" {
		cfg, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
		if err != nil {
			return nil, fmt.Errorf("loading the configured execution cluster kubeconfig %q: %w "+
				"(KUBECONFIG names the cluster workloads run in; refusing to fall back to this process's own cluster)",
				kubeconfig, err)
		}
		log.Info("using configured execution cluster", "kubeconfig", kubeconfig, "host", cfg.Host)
		return cfg, nil
	}
	cfg, inClusterErr := rest.InClusterConfig()
	if inClusterErr == nil {
		log.Info("using in-cluster credentials; workloads run in this process's own cluster", "host", cfg.Host)
		return cfg, nil
	}
	cfg, err := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(
		clientcmd.NewDefaultClientConfigLoadingRules(), &clientcmd.ConfigOverrides{}).ClientConfig()
	if err != nil {
		return nil, fmt.Errorf("no execution cluster available: not in a cluster (%w) and no ambient kubeconfig (%w)", inClusterErr, err)
	}
	log.Info("using ambient kubeconfig for the execution cluster", "host", cfg.Host)
	return cfg, nil
}
