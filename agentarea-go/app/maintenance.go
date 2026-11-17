package app

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	kdurable "github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable/temporal"
	agentsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// ErrMigrationsPending is check-migrations finding a set its migrations have not reached.
var ErrMigrationsPending = errors.New("database needs migration")

// ErrSkillJobFailed is a skills job that finished with failures.
var ErrSkillJobFailed = errors.New("some skills failed")

// runCheckMigrations is `agentarea-api check-migrations`: each migration set's applied and
// latest version; a set behind fails.
func (b *Build) runCheckMigrations(ctx context.Context, args []string) error {
	if len(args) > 0 {
		return fmt.Errorf("%w: check-migrations takes no arguments", ErrUsage)
	}
	states, err := b.migrationStates(ctx)
	if err != nil {
		return err
	}
	_, _ = fmt.Fprintln(b.stdout, "Checking migration status...")
	pending := false
	for _, st := range states {
		_, _ = fmt.Fprintf(b.stdout, "%s: current %s, head %d\n", st.Set, describeCurrent(st), st.Head)
		pending = pending || !st.UpToDate()
	}
	if pending {
		return ErrMigrationsPending
	}
	_, _ = fmt.Fprintln(b.stdout, "Database is up to date")
	return nil
}

// runStatus is `agentarea-api status` and `agentarea-worker status`: where the process would
// listen, its database and its Temporal connection, as configured. It connects to nothing.
func (b *Build) runStatus(_ context.Context, args []string) error {
	if len(args) > 0 {
		return fmt.Errorf("%w: status takes no arguments", ErrUsage)
	}
	l := config.New(b.lookup)
	dbc := db.LoadConfig(l)
	listen := serve.LoadConfig(l).Addr
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	w := b.stdout
	_, _ = fmt.Fprintln(w, "Configuration:")
	_, _ = fmt.Fprintf(w, "Listen address: %s\n", listen)
	_, _ = fmt.Fprintf(w, "Database: %s:%d\n", dbc.Host, dbc.Port)
	_, _ = fmt.Fprintf(w, "Database Name: %s\n", dbc.Name)
	opts, err := temporal.ConnectOptions(nil)
	if err != nil {
		_, _ = fmt.Fprintf(w, "Temporal Server: %v\n", err)
		return nil
	}
	tl := config.New(b.lookup)
	queues := kdurable.Load(tl).Queues
	_, _ = fmt.Fprintf(w, "Temporal Server: %s\n", opts.HostPort)
	_, _ = fmt.Fprintf(w, "Namespace: %s\n", opts.Namespace)
	if tl.Err() != nil {
		_, _ = fmt.Fprintf(w, "Task Queues: %v\n", tl.Err())
		return nil
	}
	_, _ = fmt.Fprintf(w, "Task Queue: %s\nTrigger Queue: %s\n", queues.Agent, queues.Trigger)
	return nil
}

// runValidate is `agentarea-api validate` and `agentarea-worker validate`: the configuration
// loads, the database answers, and whether each migration set is at its head. A set behind is
// reported, not a failure, as the API's validate did.
func (b *Build) runValidate(ctx context.Context, args []string) error {
	if len(args) > 0 {
		return fmt.Errorf("%w: validate takes no arguments", ErrUsage)
	}
	_, _ = fmt.Fprintln(b.stdout, "Validating configuration...")
	l := config.New(b.lookup)
	config.LoadCommon(l)
	serve.LoadConfig(l)
	kdurable.Load(l)
	if _, err := temporal.ConnectOptions(nil); err != nil {
		l.Fail("TEMPORAL_ADDRESS", err)
	}
	if err := l.Err(); err != nil {
		return fmt.Errorf("configuration: %w", err)
	}
	_, _ = fmt.Fprintln(b.stdout, "Settings loaded successfully")
	states, err := b.migrationStates(ctx)
	if err != nil {
		return err
	}
	_, _ = fmt.Fprintln(b.stdout, "Database connection successful")
	for _, st := range states {
		if st.UpToDate() {
			_, _ = fmt.Fprintf(b.stdout, "%s: migrations up to date\n", st.Set)
		} else {
			_, _ = fmt.Fprintf(b.stdout, "%s: database needs migration (current %s, head %d)\n", st.Set, describeCurrent(st), st.Head)
		}
	}
	_, _ = fmt.Fprintln(b.stdout, "Validation passed")
	return nil
}

func (b *Build) migrationStates(ctx context.Context) ([]schema.State, error) {
	l := config.New(b.lookup)
	dbc := db.LoadConfig(l)
	if err := l.Err(); err != nil {
		return nil, fmt.Errorf("configuration: %w", err)
	}
	conn, err := schema.Open(dbc.WriteURL())
	if err != nil {
		return nil, err
	}
	defer func() { _ = conn.Close() }()
	if err := conn.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("database: %w", err)
	}
	var states []schema.State
	for _, set := range b.migrationSets() {
		st, err := schema.Status(ctx, conn, set)
		if err != nil {
			return nil, err
		}
		states = append(states, st)
	}
	return states, nil
}

func describeCurrent(st schema.State) string {
	switch {
	case st.Tracked:
		return fmt.Sprint(st.Current)
	case len(st.Alembic) > 0:
		return "Alembic " + strings.Join(st.Alembic, ", ")
	}
	return "none"
}

// skillJobs are the `skills` maintenance one-shots (agentarea-api skills ...), by name.
func skillJobs() []string {
	return []string{"move-bodies-to-packages", "move-own-copies-to-packages", "delete-moved-own-copies",
		"repin-catalog-installs", "refresh-stub-installs"}
}

// runSkills is `agentarea-api skills <job>`: skill package maintenance over every workspace.
func (b *Build) runSkills(ctx context.Context, args []string) error {
	usage := fmt.Errorf("%w: skills <%s> [--dry-run] [--min-age-hours n]", ErrUsage, strings.Join(skillJobs(), "|"))
	if len(args) == 0 || !slices.Contains(skillJobs(), args[0]) {
		return usage
	}
	job := args[0]
	fs := flag.NewFlagSet("skills "+job, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	var dryRun *bool
	var minAgeHours *int
	switch job {
	case "delete-moved-own-copies":
		dryRun = fs.Bool("dry-run", false, "count what would be deleted; delete nothing")
		minAgeHours = fs.Int("min-age-hours", int(agentsservice.SkillMovedCopyMinAge/time.Hour), "keep every copy moved more recently than this")
	case "repin-catalog-installs", "refresh-stub-installs":
		dryRun = fs.Bool("dry-run", false, "report what would change; change nothing")
	}
	if err := fs.Parse(args[1:]); err != nil {
		return fmt.Errorf("%w: skills %s: %w", ErrUsage, job, err)
	}
	if fs.NArg() > 0 {
		return usage
	}
	if minAgeHours != nil && *minAgeHours < 0 {
		return fmt.Errorf("%w: --min-age-hours must be 0 or more", ErrUsage)
	}
	return b.runParts(ctx, "skills", parts{job: func(ctx context.Context, m *moduleSet) error {
		return b.skillJob(ctx, m, job, dryRun, minAgeHours)
	}})
}

func (b *Build) skillJob(ctx context.Context, m *moduleSet, job string, dryRun *bool, minAgeHours *int) error {
	w := b.stdout
	switch job {
	case "move-bodies-to-packages", "move-own-copies-to-packages":
		run, what := m.agents.SkillsMoveBodiesToPackages, "skill bodies"
		if job == "move-own-copies-to-packages" {
			run, what = m.agents.SkillsMoveOwnCopiesToPackages, "skill copies"
		}
		moved, failed, err := run(ctx)
		if err != nil {
			return err
		}
		_, _ = fmt.Fprintf(w, "Moved %d %s into packages; %d failed\n", moved, what, failed)
		if failed > 0 {
			return ErrSkillJobFailed
		}
		return nil
	case "delete-moved-own-copies":
		prefixes, files, err := m.agents.SkillsDeleteMovedOwnCopies(ctx, *dryRun, time.Duration(*minAgeHours)*time.Hour)
		if err != nil {
			return err
		}
		verb := "Deleted"
		if *dryRun {
			verb = "Would delete"
		}
		_, _ = fmt.Fprintf(w, "%s %d moved skill copies (%d files)\n", verb, prefixes, files)
		return nil
	}
	run, none, failure := m.agents.SkillsRepinCatalogInstalls, "No catalog installs", "failed"
	if job == "refresh-stub-installs" {
		run, none, failure = m.agents.SkillsRefreshStubInstalls, "No stub installs", "error"
	}
	results, err := run(ctx, *dryRun)
	if err != nil {
		return err
	}
	_, _ = io.WriteString(w, reportSkillJob(results, none))
	for _, r := range results {
		if r.Status == failure {
			return ErrSkillJobFailed
		}
	}
	return nil
}

// reportSkillJob is one line per skill, then the count of each status in first-seen order.
func reportSkillJob(results []agentsservice.SkillJobResult, none string) string {
	var b strings.Builder
	var order []string
	counts := map[string]int{}
	for _, r := range results {
		line := fmt.Sprintf("%s  %s/%s  %s", r.Status, r.WorkspaceID, r.SkillID, r.Name)
		if r.SourceURL != nil && *r.SourceURL != "" {
			line += "  " + *r.SourceURL
		}
		if r.Error != nil && *r.Error != "" {
			line += ": " + *r.Error
		}
		b.WriteString(line + "\n")
		if counts[r.Status] == 0 {
			order = append(order, r.Status)
		}
		counts[r.Status]++
	}
	if len(order) == 0 {
		b.WriteString(none + "\n")
		return b.String()
	}
	parts := make([]string, 0, len(order))
	for _, s := range order {
		parts = append(parts, fmt.Sprintf("%d %s", counts[s], s))
	}
	b.WriteString(strings.Join(parts, ", ") + "\n")
	return b.String()
}
