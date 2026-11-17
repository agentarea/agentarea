// Package temporal implements the durable ports on the Temporal Go SDK:
// connection from Temporal's envconfig contract, workers with explicit
// pollers, the executor and schedules. Payloads use the SDK's default data
// converter (encoding/json): Go workflows and activities talk only to Go.
package temporal

import (
	"context"
	"errors"
	"fmt"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"log/slog"
	"os"
	"strings"
	"time"

	"go.temporal.io/api/serviceerror"
	"go.temporal.io/api/workflowservice/v1"

	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/contrib/envconfig"
	tlog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/worker"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
)

// Client is one Temporal connection: executor, scheduler and worker factory.
type Client struct {
	sdk       client.Client
	config    durable.Config
	logger    *slog.Logger
	namespace string
	identity  string
}

var (
	_ durable.Executor  = (*Client)(nil)
	_ durable.Scheduler = (*Client)(nil)
)

// Env is where the TEMPORAL_* variables are read from; nil is the process
// environment (envconfig.EnvLookupOS).
type Env = envconfig.EnvLookup

// ConnectOptions read Temporal's client contract (config/temporal.py
// temporal_connect_config): the TOML profile
// (TEMPORAL_CONFIG_FILE, TEMPORAL_PROFILE) under TEMPORAL_ADDRESS,
// TEMPORAL_NAMESPACE, TEMPORAL_API_KEY, TEMPORAL_TLS_* and
// TEMPORAL_GRPC_META_*. Address and namespace must end up set.
func ConnectOptions(env Env) (client.Options, error) {
	opts, err := envconfig.LoadClientOptions(envconfig.LoadClientOptionsRequest{EnvLookup: env})
	if err != nil {
		return client.Options{}, fmt.Errorf("temporal client config: %w", err)
	}
	var missing []string
	if opts.HostPort == "" {
		missing = append(missing, "TEMPORAL_ADDRESS")
	}
	if opts.Namespace == "" {
		missing = append(missing, "TEMPORAL_NAMESPACE")
	}
	if len(missing) > 0 {
		return client.Options{}, fmt.Errorf("%w: set %s", ErrNotConfigured, strings.Join(missing, ", "))
	}
	return opts, nil
}

// ErrNotConfigured is returned when the address or namespace is missing.
var ErrNotConfigured = errors.New("temporal client is not configured")

// Dial connects. The sticky cache size is
// process-wide in the Go SDK and read when the first worker starts: Dial sets
// it from cfg.MaxCached, so dial before building workers.
func Dial(ctx context.Context, cfg durable.Config, env Env, logger *slog.Logger) (*Client, error) {
	opts, err := ConnectOptions(env)
	if err != nil {
		return nil, err
	}
	if logger == nil {
		logger = slog.Default()
	}
	if opts.Identity == "" {
		host, _ := os.Hostname()
		opts.Identity = fmt.Sprintf("%d@%s@", os.Getpid(), host)
	}
	opts.Logger = tlog.NewStructuredLogger(logger)
	if err := withTracing(&opts); err != nil {
		return nil, err
	}
	worker.SetStickyWorkflowCacheSize(cfg.MaxCached)
	c, err := client.DialContext(ctx, opts)
	if err != nil {
		return nil, fmt.Errorf("connect to temporal at %s (namespace %s): %w", opts.HostPort, opts.Namespace, err)
	}
	return &Client{sdk: c, config: cfg, logger: logger, namespace: opts.Namespace, identity: opts.Identity}, nil
}

// DialLazy builds a client that connects on first use, for processes that
// only start and signal workflows and must not wait for Temporal to start.
func DialLazy(cfg durable.Config, env Env, logger *slog.Logger) (*Client, error) {
	opts, err := ConnectOptions(env)
	if err != nil {
		return nil, err
	}
	if logger == nil {
		logger = slog.Default()
	}
	if opts.Identity == "" {
		host, _ := os.Hostname()
		opts.Identity = fmt.Sprintf("%d@%s@", os.Getpid(), host)
	}
	opts.Logger = tlog.NewStructuredLogger(logger)
	if err := withTracing(&opts); err != nil {
		return nil, err
	}
	c, err := client.NewLazyClient(opts)
	if err != nil {
		return nil, fmt.Errorf("temporal client for %s (namespace %s): %w", opts.HostPort, opts.Namespace, err)
	}
	return &Client{sdk: c, config: cfg, logger: logger, namespace: opts.Namespace, identity: opts.Identity}, nil
}

// SDK is the underlying client, for module workflows packages that need what
// the ports do not carry.
func (c *Client) SDK() client.Client { return c.sdk }

// Close closes the connection.
func (c *Client) Close() { c.sdk.Close() }

// NamespacePoll is how often WaitNamespace asks again for a namespace not yet registered.
const NamespacePoll = 2 * time.Second

// WaitNamespace returns once the client's namespace is registered, so a worker started beside
// Temporal (or before its namespace job ran) waits instead of exiting. Any other failure to
// describe it is returned.
func (c *Client) WaitNamespace(ctx context.Context) error {
	logged := false
	for {
		_, err := c.sdk.WorkflowService().DescribeNamespace(ctx, &workflowservice.DescribeNamespaceRequest{Namespace: c.namespace})
		if err == nil {
			if logged {
				c.logger.InfoContext(ctx, "temporal namespace is registered", "namespace", c.namespace)
			}
			return nil
		}
		if _, missing := errors.AsType[*serviceerror.NamespaceNotFound](err); !missing {
			if ctx.Err() != nil && (errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) || status.Code(err) == codes.Canceled || status.Code(err) == codes.DeadlineExceeded) {
				return nil
			}
			return fmt.Errorf("describe temporal namespace %s: %w", c.namespace, err)
		}
		if !logged {
			c.logger.WarnContext(ctx, "temporal namespace is not registered yet; waiting", "namespace", c.namespace)
			logged = true
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(NamespacePoll):
		}
	}
}
