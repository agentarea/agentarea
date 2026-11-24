package app

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	knetguard "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/netguard"
	clusterobs "github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/obs"
)

// roleBase is what every role builds before its own wiring.
type roleBase struct {
	common   config.Common
	log      *slog.Logger
	outbound *netguard.Outbound
	// ext is the extension deps every role lends: the logger and a loader of its own.
	ext ext.Deps
	// close shuts telemetry down.
	close func() error
}

// bootstrap reads what every role shares into l, reports every error l holds,
// then builds the logger, telemetry and outbound clients of the component.
func (b *Build) bootstrap(ctx context.Context, l *config.Loader, component string) (_ *roleBase, err error) {
	common := config.LoadCommon(l)
	outCfg := knetguard.LoadConfig(l)
	if err := l.Err(); err != nil {
		return nil, fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common).With("component", component)
	tel, err := clusterobs.Setup(ctx, clusterobs.Options{Enabled: common.OTelEnabled, Service: "agentarea-" + component,
		Version: buildVersion(), Environment: common.Env, Getenv: func(name string) string { v, _ := b.lookup(name); return v }})
	if err != nil {
		return nil, fmt.Errorf("telemetry: %w", err)
	}
	r := &roleBase{common: common, log: log, ext: ext.Deps{Logger: log, Config: config.New(b.lookup)},
		close: func() error { return tel.Shutdown(context.WithoutCancel(ctx)) }}
	defer func() {
		if err != nil {
			err = errors.Join(err, r.close())
		}
	}()
	trust, err := netguard.LoadTrust(outCfg.ExtraCACerts)
	if err != nil {
		return nil, fmt.Errorf("outbound trust: %w", err)
	}
	if r.outbound, err = netguard.New(outCfg, trust, log, netguard.Options{}); err != nil {
		return nil, fmt.Errorf("outbound: %w", err)
	}
	return r, nil
}

func (r *roleBase) group() *lifecycle.Group {
	return lifecycle.NewGroup(lifecycle.Options{StartupTimeout: r.common.StartupTimeout, ShutdownTimeout: r.common.ShutdownTimeout})
}
