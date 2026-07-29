package backends

import (
	"fmt"
	"log/slog"

	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	ctrl "sigs.k8s.io/controller-runtime"
)

// resolveClusterConfig picks the cluster this manager creates workloads in.
//
// An explicitly configured kubeconfig WINS over in-cluster credentials, and a
// failure to load it is fatal rather than a reason to look elsewhere. The order
// used to be the other way around — in-cluster first, kubeconfig only if that
// failed — which meant a manager running inside the control-plane cluster would
// silently create workloads there even when the operator had pointed it at a
// separate execution cluster. Untrusted MCP servers and agent sandboxes would
// land next to the control plane: exactly the arrangement a separate execution
// cluster exists to prevent, arrived at without a single error being logged.
//
// An empty setting means "use whatever cluster I am in". That is discovery, not
// a fallback: nothing was declared, so there is nothing to fall back from.
func resolveClusterConfig(kubeconfig string, logger *slog.Logger) (*rest.Config, error) {
	if kubeconfig != "" {
		cfg, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
		if err != nil {
			return nil, fmt.Errorf(
				"loading the configured execution cluster kubeconfig %q: %w "+
					"(KUBERNETES_KUBECONFIG names the cluster workloads run in; "+
					"refusing to fall back to the manager's own cluster)",
				kubeconfig, err)
		}
		logger.Info("Using configured execution cluster",
			slog.String("kubeconfig", kubeconfig),
			slog.String("host", cfg.Host))
		return cfg, nil
	}

	if cfg, err := rest.InClusterConfig(); err == nil {
		logger.Info("Using in-cluster credentials; workloads run in this manager's own cluster",
			slog.String("host", cfg.Host))
		return cfg, nil
	}

	cfg, err := ctrl.GetConfig()
	if err != nil {
		return nil, fmt.Errorf("no execution cluster available: not running in a cluster and no ambient kubeconfig found: %w", err)
	}
	logger.Info("Using ambient kubeconfig for the execution cluster", slog.String("host", cfg.Host))
	return cfg, nil
}
