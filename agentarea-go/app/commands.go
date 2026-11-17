package app

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"

	kblob "github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	kevents "github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/events"
)

// command is an operator subcommand: it runs once and exits, and takes arguments.
type command struct {
	name    string
	summary string
	run     func(b *Build, ctx context.Context, args []string) error
}

func commands() []command {
	return []command{
		{name: "init-buckets", summary: "create the storage buckets and their browser CORS allowlist", run: (*Build).runInitBuckets},
		{name: "reconcile", summary: "make the platform registries what the manifest says and sync them: reconcile [--registries-config json] [--config-file path] [--source url]... [--force] [--workspace-registries]",
			run: (*Build).runReconcile},
		{name: "dlq-replay", summary: "move dead letters back to the stream each came from: dlq-replay <dlq> [--start id] [--end id]",
			run: (*Build).runDLQReplay},
		{name: "check-migrations", summary: "report each migration set's applied and latest version; fail when one is behind",
			run: (*Build).runCheckMigrations},
		{name: "status", summary: "print the listen address, database and Temporal connection as configured",
			run: (*Build).runStatus},
		{name: "validate", summary: "load the configuration, reach the database and report whether migrations are at head",
			run: (*Build).runValidate},
		{name: "skills", summary: "skill package maintenance: skills <move-bodies-to-packages|move-own-copies-to-packages|delete-moved-own-copies|repin-catalog-installs|refresh-stub-installs> [--dry-run] [--min-age-hours n]",
			run: (*Build).runSkills},
		{name: "kratos-jwks", summary: "create the Secret with the key Kratos signs session JWTs with, once: kratos-jwks --secret name --kid id --namespace ns",
			run: (*Build).runKratosJWKS},
	}
}

// coreNames are the roles' and commands' names, which no extension may take.
func coreNames() []string {
	var out []string
	for _, r := range roles() {
		out = append(out, r.name)
	}
	for _, c := range commands() {
		out = append(out, c.name)
	}
	return out
}

// runInitBuckets is bucket_init.py: AGENTAREA_S3_BUCKETS each created (one already there is
// fine) and given AGENTAREA_S3_CORS_ORIGINS, so browsers can PUT presigned uploads.
func (b *Build) runInitBuckets(ctx context.Context, args []string) error {
	if len(args) > 0 {
		return fmt.Errorf("%w: init-buckets takes no arguments", ErrUsage)
	}
	l := config.New(b.lookup)
	cfg := kblob.LoadConfig(l)
	buckets := l.ListEnv("AGENTAREA_S3_BUCKETS", nil)
	if len(buckets) == 0 {
		l.Fail("AGENTAREA_S3_BUCKETS", errors.New("names no bucket"))
	}
	origins := l.ListEnv("AGENTAREA_S3_CORS_ORIGINS", nil)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	if err := blob.New(cfg).InitBuckets(ctx, buckets, origins); err != nil {
		return err
	}
	_, _ = fmt.Fprintf(b.stdout, "Buckets %v ready; browser uploads allowed from %v\n", buckets, origins)
	return nil
}

// runDLQReplay is `agentarea-api dlq-replay`: each dead letter with an id in [--start, --end]
// moved once back to its source stream or partition.
func (b *Build) runDLQReplay(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("dlq-replay", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	start := fs.String("start", "-", "first message id to replay, inclusive ('-': oldest)")
	end := fs.String("end", "+", "last message id to replay, inclusive ('+': newest)")
	var positional []string
	for len(args) > 0 {
		if err := fs.Parse(args); err != nil {
			return fmt.Errorf("%w: dlq-replay: %w", ErrUsage, err)
		}
		args = fs.Args()
		if len(args) > 0 {
			positional, args = append(positional, args[0]), args[1:]
		}
	}
	if len(positional) != 1 {
		return fmt.Errorf("%w: dlq-replay <dlq> [--start id] [--end id]", ErrUsage)
	}
	dlq := positional[0]
	l := config.New(b.lookup)
	common := config.LoadCommon(l)
	cfg := kevents.LoadConfig(l)
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	routes, err := kevents.RoutesForDLQ(kevents.ConfiguredRoutes(cfg.Partitions), dlq)
	if err != nil {
		return fmt.Errorf("%w: %w", ErrUsage, err)
	}
	log := newLogger(b.stderr, common).With("component", "dlq-replay")
	client, err := events.NewClient(cfg.RedisURL)
	if err != nil {
		return fmt.Errorf("redis: %w", err)
	}
	defer func() { _ = client.Close() }()
	broker, err := events.NewBroker(client, cfg.Namespace, log)
	if err != nil {
		return err
	}
	targets := make([]string, 0, len(routes))
	for _, r := range routes {
		targets = append(targets, r.Stream)
	}
	res, err := kevents.ReplayDeadLetters(ctx, broker, log, dlq, targets, *start, *end, 0)
	if err != nil {
		return err
	}
	_, _ = fmt.Fprintf(b.stdout, "Replayed %d dead letters from %s; %d left in place\n", res.Moved, dlq, res.Skipped)
	return nil
}
