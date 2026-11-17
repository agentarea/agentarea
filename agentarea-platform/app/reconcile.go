package app

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"sigs.k8s.io/yaml"

	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

// ErrReconcileFailed is a reconcile run in which a platform registry failed.
var ErrReconcileFailed = errors.New("reconcile failed")

type repeated []string

func (r *repeated) String() string     { return strings.Join(*r, ",") }
func (r *repeated) Set(v string) error { *r = append(*r, v); return nil }

// runReconcile is `agentarea-api reconcile`: the platform registries made what
// the manifest says (REGISTRIES_CONFIG, --config-file, --source) and synced.
func (b *Build) runReconcile(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("reconcile", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	envConfig, _ := b.lookup("REGISTRIES_CONFIG")
	registries := fs.String("registries-config", envConfig, "JSON array of registry definitions (or REGISTRIES_CONFIG)")
	configFile := fs.String("config-file", "", "path to a YAML/JSON manifest listing registry sources")
	force := fs.Bool("force", false, "re-read every source even if its ETag is the one last applied")
	workspace := fs.Bool("workspace-registries", false, "also sync every active registry a workspace added")
	var sources repeated
	fs.Var(&sources, "source", "registry source file/URL (repeatable); its type is detected")
	if err := fs.Parse(args); err != nil {
		return fmt.Errorf("%w: reconcile: %w", ErrUsage, err)
	}
	if fs.NArg() > 0 {
		return fmt.Errorf("%w: reconcile takes no positional arguments", ErrUsage)
	}
	manifest, err := reconcileManifest(*registries, *configFile, sources, os.ReadFile)
	if err != nil {
		return err
	}
	if len(manifest) == 0 && !*workspace {
		_, _ = fmt.Fprintln(b.stdout, "No registry config provided (set REGISTRIES_CONFIG or use --source)")
		return nil
	}
	opts := catalogapi.ReconcileOptions{Manifest: manifest, Force: *force, WorkspaceRegistries: *workspace}
	return b.runParts(ctx, "reconcile", parts{reconcile: &opts})
}

// reconcileManifest joins the manifest's three sources in the order Python
// read them: the JSON config, the file, then each --source.
func reconcileManifest(registries, configFile string, sources []string, read func(string) ([]byte, error)) ([]map[string]any, error) {
	var manifest []map[string]any
	if registries != "" {
		if err := json.Unmarshal([]byte(registries), &manifest); err != nil {
			return nil, fmt.Errorf("REGISTRIES_CONFIG must be a JSON array of registries: %w", err)
		}
	}
	if configFile != "" {
		data, err := read(configFile)
		if err != nil {
			return nil, fmt.Errorf("--config-file %s: %w", configFile, err)
		}
		var entries []map[string]any
		if err := yaml.Unmarshal(data, &entries); err != nil {
			return nil, fmt.Errorf("--config-file %s must contain a list of registries: %w", configFile, err)
		}
		manifest = append(manifest, entries...)
	}
	for _, src := range sources {
		name := src[strings.LastIndex(src, "/")+1:]
		if !strings.HasPrefix(src, "http") {
			name = strings.TrimSuffix(filepath.Base(src), filepath.Ext(src))
		}
		manifest = append(manifest, map[string]any{"name": name, "source_url": src})
	}
	return manifest, nil
}

// reportReconcile prints the run as Python did; a failed platform registry
// fails the command.
func reportReconcile(w io.Writer, total int, res catalogapi.ReconcileResult, workspace bool) error {
	if workspace {
		_, _ = fmt.Fprintf(w, "\nWorkspace registries: %d synced, %d failed\n", len(res.WorkspaceSynced), len(res.WorkspaceFailed))
		for _, name := range sortedKeys(res.WorkspaceFailed) {
			_, _ = fmt.Fprintf(w, "  - %s: %s\n", name, res.WorkspaceFailed[name])
		}
	}
	for _, name := range res.Skipped {
		_, _ = fmt.Fprintf(w, "  WARNING: skipped, another reconcile was syncing: %s\n", name)
	}
	_, _ = fmt.Fprintf(w, "\nReconcile complete: %d succeeded, %d failed, %d skipped (out of %d)\n",
		len(res.Succeeded), len(res.Failed), len(res.Skipped), total)
	if len(res.Failed) == 0 {
		return nil
	}
	for _, name := range sortedKeys(res.Failed) {
		_, _ = fmt.Fprintf(w, "  - %s: %s\n", name, res.Failed[name])
	}
	return fmt.Errorf("%w: %d of %d registries", ErrReconcileFailed, len(res.Failed), total)
}

func sortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}
