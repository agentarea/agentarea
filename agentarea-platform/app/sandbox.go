package app

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/ext"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	knetguard "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/builtin"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/workspace"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/plane"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/events"
)

// runSandbox is the sandbox role (sandbox-runner): it consumes sandbox
// executions on the configured provider, the warm pool unless
// AGENTAREA_SANDBOX_PROVIDER names an external one. It holds no database; the
// workload hooks' sandbox observers attach to the runtime it runs.
func (b *Build) runSandbox(ctx context.Context) (err error) {
	l := config.New(b.lookup)
	sc := plane.LoadConfig(l)
	rb, err := b.bootstrap(ctx, l, "sandbox")
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, rb.close()) }()
	exts, err := b.resolveWorkloadHooks(ctx, rb.ext)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, exts.Close()) }()
	rdb, err := events.NewClient(sc.RedisURL)
	if err != nil {
		return fmt.Errorf("sandbox redis: %w", err)
	}
	defer func() { err = errors.Join(err, rdb.Close()) }()
	sb, err := openSandbox(ctx, sc, rdb, plane.BuiltinKubernetes, rb.outbound, sandboxHooks(exts.WorkloadHooks, true), rb.log)
	if err != nil {
		return err
	}
	if err := attachWorkloads(ctx, exts.WorkloadHooks, ext.Workloads{Redis: rdb, SandboxProvider: sb.Provider}); err != nil {
		return err
	}
	g := rb.group()
	g.Add(&runComponent{name: "sandbox runner", run: sb.Run, log: rb.log})
	return g.Run(ctx)
}

// openSandbox builds the plane's infrastructure over the process's Redis (the
// workspace object store, the warm pool's cluster client when it runs) and
// opens the plane over it.
func openSandbox(ctx context.Context, sc plane.Config, rdb *redis.Client, builtinKind string, out knetguard.Clients, hooks []plane.Hook, log *slog.Logger) (*plane.Plane, error) {
	objects, err := sandboxObjectStore(ctx, sc.Workspace, out)
	if err != nil {
		return nil, err
	}
	var cluster builtin.Cluster
	if sc.Builtin(builtinKind) == plane.BuiltinKubernetes {
		if cluster, err = builtin.Clientset(sc.Kubeconfig, log); err != nil {
			return nil, err
		}
	}
	return plane.Open(sc, builtinKind, plane.Deps{Redis: rdb, S3: objects, Kubernetes: cluster, Out: out, Hooks: hooks, Log: log})
}

// sandboxObjectStore is the S3 client of task workspaces and published
// artifacts: static credentials when the platform names them, the SDK's own
// chain when it names neither (an IAM role).
func sandboxObjectStore(ctx context.Context, c workspace.RepositoryConfig, out knetguard.Clients) (*s3.Client, error) {
	options := []func(*awsconfig.LoadOptions) error{
		awsconfig.WithRegion(c.Region),
		awsconfig.WithHTTPClient(&http.Client{Transport: out.Transport(knetguard.Vendor)}),
	}
	if c.AccessKey != "" || c.SecretKey != "" {
		if c.AccessKey == "" || c.SecretKey == "" {
			return nil, errors.New("sandbox object store: set both AGENTAREA_S3_ACCESS_KEY and AGENTAREA_S3_SECRET_KEY, or neither")
		}
		options = append(options, awsconfig.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(c.AccessKey, c.SecretKey, "")))
	}
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, options...)
	if err != nil {
		return nil, fmt.Errorf("sandbox object store: %w", err)
	}
	return s3.NewFromConfig(awsCfg, func(o *s3.Options) {
		o.UsePathStyle = c.ForcePathStyle
		if c.Endpoint != "" {
			o.BaseEndpoint = aws.String(c.Endpoint)
		}
	}), nil
}
