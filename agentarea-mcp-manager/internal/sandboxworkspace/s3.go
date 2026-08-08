package sandboxworkspace

import (
	"context"
	"fmt"

	"github.com/agentarea/mcp-manager/internal/workspace"
)

const inputPrefix = "inputs"

type hydrationRepository interface {
	PrepareCurrentHydration(context.Context, string, string, string) (workspace.Hydration, error)
}

// S3Provider resolves the immutable Task Input Manifest maintained in object
// storage. The live directory is still owned by the selected sandbox runtime;
// the returned hydration plan is materialized by the Go runtime wrapper.
type S3Provider struct {
	repository hydrationRepository
}

func NewS3Provider(repository hydrationRepository) (*S3Provider, error) {
	if repository == nil {
		return nil, fmt.Errorf("workspace hydration repository is required")
	}
	return &S3Provider{repository: repository}, nil
}

func NewS3ProviderFromConfig(ctx context.Context, cfg workspace.RepositoryConfig) (*S3Provider, error) {
	repository, err := workspace.NewRepositoryFromConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	return NewS3Provider(repository)
}

func (p *S3Provider) Ensure(ctx context.Context, workspaceID, taskID string) (*Mount, error) {
	hydration, err := p.repository.PrepareCurrentHydration(ctx, workspaceID, taskID, inputPrefix)
	if err != nil {
		return nil, err
	}
	return &Mount{
		WorkspaceID:    workspaceID,
		TaskID:         taskID,
		Root:           "/workspace",
		Generation:     hydration.Generation,
		ManifestSHA256: hydration.ManifestSHA256,
		RevisionSHA256: hydration.RevisionSHA256,
		Hydration:      hydration,
	}, nil
}

// The first implementation uses ephemeral live files plus immutable S3
// inputs/artifacts. Full-workspace archival is a separate operation and must
// fail loudly until a provider that can snapshot its volume is configured.
func (*S3Provider) Archive(context.Context, string, string) error {
	return fmt.Errorf("%w: S3 manifest provider cannot snapshot a live runtime volume", ErrLifecycleUnsupported)
}

func (*S3Provider) Restore(context.Context, string, string) error {
	return fmt.Errorf("%w: no full workspace archive exists", ErrLifecycleUnsupported)
}

func (*S3Provider) Delete(context.Context, string, string) error {
	return fmt.Errorf("%w: durable task inputs are retention-managed", ErrLifecycleUnsupported)
}
