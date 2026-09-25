package artifactstore

import "context"

// Publication describes an artifact whose object write has succeeded.
// ObjectKey is the trusted storage key inside the configured bucket.
type Publication struct {
	WorkspaceID string
	TaskID      string
	ObjectKey   string
	SizeBytes   int64
}

// PublicationObserver is told about each successful publication before the
// publish call returns. Its error fails the publish call; the stored object
// is kept.
type PublicationObserver interface {
	Published(context.Context, Publication) error
}

// SetPublicationObserver must be called before the repository serves requests.
func (r *Repository) SetPublicationObserver(observer PublicationObserver) { r.published = observer }

// ObjectStore exposes the normalized configuration and the already-built client
// to composition code, so an extension reuses this repository's credentials.
func (r *Repository) ObjectStore() (Config, ObjectStoreClient) { return r.cfg, r.client }

// IsArtifactID reports whether id has the artifact identifier format used in
// object keys.
func IsArtifactID(id string) bool { return artifactIDPattern.MatchString(id) }

func (r *Repository) observePublication(ctx context.Context, workspaceID, taskID string, artifact Artifact) error {
	if r.published == nil {
		return nil
	}
	return r.published.Published(ctx, Publication{
		WorkspaceID: workspaceID, TaskID: taskID, ObjectKey: artifact.objectKey, SizeBytes: artifact.Size,
	})
}
