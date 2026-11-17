package app

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	knetguard "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/operator"
)

func (b *Build) runOperator(ctx context.Context) error {
	return b.runParts(ctx, "operator", parts{operator: true})
}

// addOperator watches the declared resources in the namespace this process runs in (or KUBECONFIG's context).
func addOperator(g *lifecycle.Group, m *moduleSet, out knetguard.Clients, log *slog.Logger) error {
	cfg, namespace, err := operator.ClusterConfig()
	if err != nil {
		return err
	}
	secrets, err := operator.NewSecrets(cfg)
	if err != nil {
		return err
	}
	r := operator.New(operator.Deps{
		Catalog: m.catalog.Platform(), Models: m.models.Declared(), Connections: m.connections.Platform(),
		Egress: m.governance.EgressExits(), Secrets: secrets, Log: log,
		PlatformHTTP:  &http.Client{Transport: out.Transport(knetguard.Vendor)},
		WorkspaceHTTP: &http.Client{Transport: out.Transport(knetguard.Member)},
	})
	c, err := operator.NewController(cfg, namespace, r, log)
	if err != nil {
		return err
	}
	g.Add(lifecycle.Loop("operator", c.Run))
	return nil
}
