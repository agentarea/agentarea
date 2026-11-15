// Package app is the composition root of agentarea: it parses the subcommand
// (the role), loads configuration, builds the kernel adapters of the
// cluster profile, constructs the modules the role needs, passes each module
// the others it declared, and runs them under one lifecycle.
//
// app and ext are the public packages of the module. Nothing under internal/
// imports app.
package app

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/agentarea/agentarea/agentarea-go/ext"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// Build is one distribution of the binary: the open core with the extensions
// it was given. The open build passes none.
type Build struct {
	ext    ext.Set
	stdout io.Writer
	stderr io.Writer
	lookup config.Lookup
}

// Default is the open core plus the given extensions.
func Default(opts ...ext.Option) *Build {
	b := &Build{stdout: os.Stdout, stderr: os.Stderr, lookup: os.LookupEnv}
	for _, o := range opts {
		o(&b.ext)
	}
	return b
}

// ErrUsage is a bad command line; Main exits 2.
var ErrUsage = errors.New("usage")

// ErrNotImplemented is a role the Go backend does not run yet; the Python
// service still does.
var ErrNotImplemented = errors.New("not implemented in the Go backend yet")

// Main runs the role named by os.Args[1] and returns the process exit code:
// 0, 1 on failure, 2 on a usage error.
func Main(b *Build) int {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	return b.exitCode(b.Run(ctx, os.Args[1:]))
}

func (b *Build) exitCode(err error) int {
	if err == nil {
		return 0
	}
	_, _ = fmt.Fprintln(b.stderr, "agentarea:", err)
	if errors.Is(err, ErrUsage) {
		return 2
	}
	return 1
}

// Run dispatches one subcommand.
func (b *Build) Run(ctx context.Context, args []string) error {
	if err := b.check(); err != nil {
		return err
	}
	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
		b.usage()
		return fmt.Errorf("%w: name a role", ErrUsage)
	}
	name, rest := args[0], args[1:]
	for _, r := range roles() {
		if r.name == name {
			return b.runRole(ctx, r, rest)
		}
	}
	for _, c := range commands() {
		if c.name == name {
			return c.run(b, ctx, rest)
		}
	}
	for _, c := range b.ext.Commands {
		if c.Name == name {
			deps, closeDeps, err := b.ExtensionDeps(ctx)
			if err != nil {
				return err
			}
			defer closeDeps()
			return c.Run(ctx, deps, rest)
		}
	}
	for _, r := range b.ext.Roles {
		if r.Name == name {
			if len(rest) > 0 {
				return fmt.Errorf("%w: %s takes no arguments", ErrUsage, name)
			}
			deps, closeDeps, err := b.ExtensionDeps(ctx)
			if err != nil {
				return err
			}
			defer closeDeps()
			return r.Run(ctx, deps)
		}
	}
	b.usage()
	return fmt.Errorf("%w: unknown subcommand %q", ErrUsage, name)
}

// check refuses a build whose extensions are invalid or shadow a core role.
func (b *Build) check() error {
	errs := []error{b.ext.Err()}
	for _, core := range coreNames() {
		for _, c := range b.ext.Commands {
			if c.Name == core {
				errs = append(errs, fmt.Errorf("ext: command %q shadows a core role", c.Name))
			}
		}
		for _, x := range b.ext.Roles {
			if x.Name == core {
				errs = append(errs, fmt.Errorf("ext: role %q shadows a core role", x.Name))
			}
		}
	}
	return errors.Join(errs...)
}

func (b *Build) runRole(ctx context.Context, r role, args []string) error {
	if len(args) > 0 {
		return fmt.Errorf("%w: %s takes no arguments", ErrUsage, r.name)
	}
	switch r.name {
	case "serve":
		return b.runServe(ctx)
	case "migrate":
		return b.runMigrate(ctx)
	case "worker":
		return b.runWorker(ctx)
	case "events":
		return b.runEvents(ctx)
	case "mcp":
		return b.runMCP(ctx)
	case "all":
		return b.runAll(ctx)
	}
	return fmt.Errorf("role %s: %w (%s)", r.name, ErrNotImplemented, r.lands)
}

func newLogger(w io.Writer, c config.Common) *slog.Logger {
	opts := &slog.HandlerOptions{Level: logLevel(c.LogLevel)}
	if c.LogFormat == "text" {
		return slog.New(slog.NewTextHandler(w, opts))
	}
	return slog.New(slog.NewJSONHandler(w, opts))
}

func logLevel(name string) slog.Level {
	switch strings.ToUpper(name) {
	case "DEBUG":
		return slog.LevelDebug
	case "WARNING":
		return slog.LevelWarn
	case "ERROR", "CRITICAL":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func (b *Build) usage() {
	_, _ = fmt.Fprintln(b.stderr, "usage: agentarea <role> [args]")
	for _, r := range roles() {
		_, _ = fmt.Fprintf(b.stderr, "  %-10s %s\n", r.name, r.summary)
	}
	for _, c := range commands() {
		_, _ = fmt.Fprintf(b.stderr, "  %-10s %s\n", c.name, c.summary)
	}
	for _, c := range b.ext.Commands {
		_, _ = fmt.Fprintf(b.stderr, "  %-10s %s (extension)\n", c.Name, c.Summary)
	}
	for _, r := range b.ext.Roles {
		_, _ = fmt.Fprintf(b.stderr, "  %-10s %s (extension role)\n", r.Name, r.Summary)
	}
}
