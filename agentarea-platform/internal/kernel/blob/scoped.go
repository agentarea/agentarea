package blob

import (
	"context"
	"errors"
	"fmt"
	"io"
	"iter"
	"strings"
	"time"
	"unicode/utf8"
)

// MaxKeyBytes is S3's key limit, and the bound ArtifactService holds a
// workspace key to.
const MaxKeyBytes = 1024

// MaxWritePathBytes bounds a path that is written (not read), so the paths
// Python can never write cannot arrive through Go either.
const MaxWritePathBytes = 900

// ErrInvalidPath is a path that cannot name an object: empty, a ".." segment,
// a control character, or a key past MaxKeyBytes.
var ErrInvalidPath = errors.New("invalid artifact path")

// WorkspacePrefix is where a workspace's files live in the artifacts bucket.
func WorkspacePrefix(workspaceID string) (string, error) {
	if workspaceID == "" {
		return "", errors.New("workspace_id is required")
	}
	return "workspaces/" + workspaceID + "/", nil
}

// Scoped confines a Store to one key prefix: callers name paths, never keys,
// and a path cannot climb out (artifacts/service.py _key). Leading slashes are
// stripped, as Python's lstrip("/") does.
type Scoped struct {
	store  Store
	prefix string
}

// NewScoped confines store to prefix, which must end in "/".
func NewScoped(store Store, prefix string) (*Scoped, error) {
	if !strings.HasSuffix(prefix, "/") {
		return nil, fmt.Errorf("scope prefix %q must end in /", prefix)
	}
	return &Scoped{store: store, prefix: prefix}, nil
}

// ForWorkspace is the workspace's file store.
func ForWorkspace(store Store, workspaceID string) (*Scoped, error) {
	p, err := WorkspacePrefix(workspaceID)
	if err != nil {
		return nil, err
	}
	return NewScoped(store, p)
}

// Key is the storage key of path.
func (s *Scoped) Key(path string) (string, error) {
	clean := strings.TrimLeft(path, "/")
	if clean == "" {
		return "", fmt.Errorf("%w: path is empty", ErrInvalidPath)
	}
	if !utf8.ValidString(clean) {
		return "", fmt.Errorf("%w: path is not valid UTF-8", ErrInvalidPath)
	}
	for _, seg := range strings.Split(clean, "/") {
		if seg == ".." {
			return "", fmt.Errorf("%w: path may not contain '..' segments: %q", ErrInvalidPath, path)
		}
	}
	for _, r := range clean {
		if r < 0x20 || r == 0x7f {
			return "", fmt.Errorf("%w: path may not contain control characters: %q", ErrInvalidPath, path)
		}
	}
	key := s.prefix + clean
	if len(key) > MaxKeyBytes {
		return "", fmt.Errorf("%w: path is too long: its storage key exceeds %d bytes", ErrInvalidPath, MaxKeyBytes)
	}
	return key, nil
}

// Path is the path of a storage key under this scope, false for a key outside it.
func (s *Scoped) Path(key string) (string, bool) { return strings.CutPrefix(key, s.prefix) }

func (s *Scoped) writeKey(path string) (string, error) {
	key, err := s.Key(path)
	if err != nil {
		return "", err
	}
	if len(strings.TrimLeft(path, "/")) > MaxWritePathBytes {
		return "", fmt.Errorf("%w: path is too long: a written path may not exceed %d bytes", ErrInvalidPath, MaxWritePathBytes)
	}
	return key, nil
}

func (s *Scoped) Put(ctx context.Context, path string, body io.Reader, size int64, opts PutOptions) error {
	key, err := s.writeKey(path)
	if err != nil {
		return err
	}
	return s.store.Put(ctx, key, body, size, opts)
}

func (s *Scoped) Get(ctx context.Context, path string) (io.ReadCloser, Info, error) {
	key, err := s.Key(path)
	if err != nil {
		return nil, Info{}, err
	}
	rc, info, err := s.store.Get(ctx, key)
	info.Key, _ = s.Path(info.Key)
	return rc, info, err
}

func (s *Scoped) Stat(ctx context.Context, path string) (Info, error) {
	key, err := s.Key(path)
	if err != nil {
		return Info{}, err
	}
	info, err := s.store.Stat(ctx, key)
	info.Key, _ = s.Path(info.Key)
	return info, err
}

func (s *Scoped) Delete(ctx context.Context, path string) error {
	key, err := s.Key(path)
	if err != nil {
		return err
	}
	return s.store.Delete(ctx, key)
}

// Copy moves bytes between two paths of this scope.
func (s *Scoped) Copy(ctx context.Context, src, dst string, opts CopyOptions) error {
	from, err := s.Key(src)
	if err != nil {
		return err
	}
	to, err := s.writeKey(dst)
	if err != nil {
		return err
	}
	return s.store.Copy(ctx, from, to, opts)
}

// List yields the objects under a path prefix ("" for the whole scope), Key
// relative to the scope; the scope's own directory marker is skipped.
func (s *Scoped) List(ctx context.Context, prefix string) iter.Seq2[Info, error] {
	return func(yield func(Info, error) bool) {
		full, err := s.listPrefix(prefix)
		if err != nil {
			yield(Info{}, err)
			return
		}
		for info, err := range s.store.List(ctx, full) {
			if err != nil {
				yield(Info{}, err)
				return
			}
			rel, _ := s.Path(info.Key)
			if rel == "" {
				continue
			}
			info.Key = rel
			if !yield(info, nil) {
				return
			}
		}
	}
}

// ListDir is one delimited level under a path prefix; folders keep their trailing slash.
func (s *Scoped) ListDir(ctx context.Context, prefix string) ([]Info, []string, error) {
	full, err := s.listPrefix(prefix)
	if err != nil {
		return nil, nil, err
	}
	objects, folders, err := s.store.ListDir(ctx, full)
	if err != nil {
		return nil, nil, err
	}
	out := objects[:0]
	for _, o := range objects {
		rel, _ := s.Path(o.Key)
		if rel == "" {
			continue
		}
		o.Key = rel
		out = append(out, o)
	}
	for i, f := range folders {
		folders[i], _ = s.Path(f)
	}
	return out, folders, nil
}

func (s *Scoped) listPrefix(prefix string) (string, error) {
	clean := strings.TrimLeft(prefix, "/")
	for _, seg := range strings.Split(clean, "/") {
		if seg == ".." {
			return "", fmt.Errorf("%w: prefix may not contain '..' segments: %q", ErrInvalidPath, prefix)
		}
	}
	return s.prefix + clean, nil
}

func (s *Scoped) PresignGet(ctx context.Context, path string, ttl time.Duration) (Presigned, error) {
	key, err := s.Key(path)
	if err != nil {
		return Presigned{}, err
	}
	return s.store.PresignGet(ctx, key, ttl)
}

func (s *Scoped) PresignPut(ctx context.Context, path string, opts PutOptions, ttl time.Duration) (Presigned, error) {
	key, err := s.writeKey(path)
	if err != nil {
		return Presigned{}, err
	}
	return s.store.PresignPut(ctx, key, opts, ttl)
}
