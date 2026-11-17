package app

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"

	knetguard "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/operator"
)

// ErrDeclareFailed is a declare run in which a resource did not sync.
var ErrDeclareFailed = errors.New("declare failed")

type declareJob struct {
	resources []operator.Declared
	secrets   operator.SecretReader
}

// runDeclare is `agentarea declare`: the operator's resources (LLMProviderConfig,
// PlatformConnection, PlatformEgressExit) read from manifests instead of a cluster and
// reconciled once, for an install without Kubernetes.
func (b *Build) runDeclare(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("declare", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	var files repeated
	fs.Var(&files, "f", "manifest file or directory of manifests (repeatable)")
	secretsDir := fs.String("secrets-dir", "", "directory holding each referenced Secret as <name>/<key>")
	namespace := fs.String("namespace", "default", "namespace of a resource whose metadata names none")
	if err := fs.Parse(args); err != nil {
		return fmt.Errorf("%w: declare: %w", ErrUsage, err)
	}
	if fs.NArg() > 0 || len(files) == 0 {
		return fmt.Errorf("%w: declare -f <file|dir>... [--secrets-dir dir] [--namespace ns]", ErrUsage)
	}
	resources, err := operator.ReadManifests(files, *namespace)
	if err != nil {
		return err
	}
	if len(resources) == 0 {
		return fmt.Errorf("%w: no declared resource in %v", ErrUsage, []string(files))
	}
	return b.runParts(ctx, "declare", parts{declare: &declareJob{resources: resources, secrets: operator.DirSecrets{Dir: *secretsDir}}})
}

func runDeclared(ctx context.Context, w io.Writer, m *moduleSet, out knetguard.Clients, log *slog.Logger, job declareJob) error {
	r := newReconciler(m, out, job.secrets, log)
	failed := 0
	for _, d := range job.resources {
		o := r.Apply(ctx, d)
		phase, _ := o.Status["phase"].(string)
		message, _ := o.Status["message"].(string)
		_, _ = fmt.Fprintf(w, "%s %s/%s: %s %s\n", d.Kind, d.Namespace, d.Name, phase, message)
		if phase != "Synced" {
			failed++
		}
	}
	if failed > 0 {
		return fmt.Errorf("%w: %d of %d resources", ErrDeclareFailed, failed, len(job.resources))
	}
	return nil
}
