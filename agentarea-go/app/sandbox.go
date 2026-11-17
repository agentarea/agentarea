package app

import (
	"context"
	"errors"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/ext"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/plane"
	clusterobs "github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/obs"
)

// runSandbox is the sandbox role (sandbox-runner): it consumes sandbox
// executions on the configured provider, the warm pool unless
// AGENTAREA_SANDBOX_PROVIDER names an external one. It holds no database; the
// workload hooks' sandbox observers attach to the runtime it runs.
func (b *Build) runSandbox(ctx context.Context) (err error) {
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	sc := plane.LoadConfig(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	log := newLogger(b.stderr, common).With("component", "sandbox")
	tel, err := clusterobs.Setup(ctx, clusterobs.Options{Enabled: common.OTelEnabled, Service: "agentarea-sandbox",
		Version: buildVersion(), Environment: common.Env, Getenv: func(name string) string { v, _ := b.lookup(name); return v }})
	if err != nil {
		return fmt.Errorf("telemetry: %w", err)
	}
	defer func() { err = errors.Join(err, tel.Shutdown(context.WithoutCancel(ctx))) }()
	exts, err := b.resolveWorkloadHooks(ctx, ext.Deps{Logger: log, Config: config.New(b.lookup)})
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, exts.Close()) }()
	sb, err := plane.Open(ctx, sc, plane.BuiltinKubernetes, sandboxHooks(exts.WorkloadHooks, true), log)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, sb.Close()) }()
	if err := attachWorkloads(ctx, exts.WorkloadHooks, ext.Workloads{Redis: sb.Redis(), SandboxProvider: sb.Provider}); err != nil {
		return err
	}
	g := lifecycle.NewGroup(lifecycle.Options{StartupTimeout: common.StartupTimeout, ShutdownTimeout: common.ShutdownTimeout})
	g.Add(&runComponent{name: "sandbox runner", run: sb.Run, log: log})
	return g.Run(ctx)
}
