package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// InvalidPathError is InvalidArtifactPathError (422 invalid_artifact_path).
type InvalidPathError struct{ Msg string }

func (e *InvalidPathError) Error() string { return e.Msg }

// ErrFileNotFound is FileNotFoundError from the artifact store.
var ErrFileNotFound = api.ErrFileNotFound

// ErrIntegrity is ArtifactIntegrityError: bytes that cannot be verified.
var ErrIntegrity = errors.New("artifact integrity")

func isSHA256(s string) bool {
	if len(s) != 64 {
		return false
	}
	for i := range len(s) {
		c := s[i]
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

// pathErr turns the blob scope's refusal into InvalidPathError with
// Python's message.
func pathErr(err error) error {
	if errors.Is(err, blob.ErrInvalidPath) {
		msg := strings.TrimPrefix(err.Error(), blob.ErrInvalidPath.Error()+": ")
		return &InvalidPathError{Msg: pyPathMessage(msg)}
	}
	return err
}

// pyPathMessage rewrites the Go-quoted path in a blob message as Python's repr.
func pyPathMessage(msg string) string {
	re := regexp.MustCompile(`^(path may not contain (?:'\.\.' segments|control characters)): (".*")$`)
	m := re.FindStringSubmatch(msg)
	if m == nil {
		return msg
	}
	var p string
	if _, err := fmt.Sscanf(m[2], "%q", &p); err != nil {
		return msg
	}
	return m[1] + ": " + domain.PyRepr(p)
}

// Object is ArtifactObject.
type Object struct {
	Path         string
	Size         int64
	ContentType  string
	LastModified *string
}

// Restored is RestoredArtifact.
type Restored struct {
	Path, RestoredFrom string
	ArchivedCurrent    *string
}

// Head is ArtifactService.head.
type Head struct {
	Size        int64
	ContentType string
	SHA256      string
}

// Verified is a stream verified into a spool before its first byte is read.
type Verified struct {
	Body        io.ReadCloser
	ContentType string
	Size        int64
}

// Artifacts is ArtifactService over the artifacts bucket. Events are
// recorded only for calls given an actor.
type Artifacts struct {
	Blob       blob.Store
	Record     func(ctx context.Context, workspaceID, path, action string, actor *api.Actor)
	RecordMove func(ctx context.Context, workspaceID, source, destination string, actor *api.Actor)
	Now        func() time.Time
}

func (a *Artifacts) scope(workspaceID string) (*blob.Scoped, error) {
	return blob.ForWorkspace(a.Blob, workspaceID)
}

func (a *Artifacts) key(workspaceID, path string) (string, error) {
	s, err := a.scope(workspaceID)
	if err != nil {
		return "", err
	}
	k, err := s.Key(path)
	return k, pathErr(err)
}

func (a *Artifacts) writeKey(workspaceID, path string) (string, error) {
	k, err := a.key(workspaceID, path)
	if err != nil {
		return "", err
	}
	if len(strings.TrimLeft(path, "/")) > domain.MaxWritePathBytes {
		return "", &InvalidPathError{Msg: fmt.Sprintf("path is too long: a written path may not exceed %d bytes", domain.MaxWritePathBytes)}
	}
	return k, nil
}

func (a *Artifacts) record(ctx context.Context, workspaceID, path, action string, actor *api.Actor) {
	if actor == nil || a.Record == nil {
		return
	}
	a.Record(ctx, workspaceID, strings.TrimLeft(path, "/"), action, actor)
}

// Put writes a whole object with its digest as metadata and checksum.
func (a *Artifacts) Put(ctx context.Context, workspaceID, path string, data []byte, contentType string, actor *api.Actor) (Object, error) {
	key, err := a.writeKey(workspaceID, path)
	if err != nil {
		return Object{}, err
	}
	if contentType == "" {
		contentType = domain.ContentTypeOf(path)
	}
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	existed := false
	if actor != nil {
		if existed, err = a.Exists(ctx, workspaceID, path); err != nil {
			return Object{}, err
		}
	}
	if err := a.Blob.Put(ctx, key, bytes.NewReader(data), int64(len(data)), blob.PutOptions{
		ContentType: contentType, Metadata: map[string]string{"sha256": digest}, SHA256: digest,
	}); err != nil {
		return Object{}, err
	}
	action := domain.ActionCreated
	if existed {
		action = domain.ActionModified
	}
	a.record(ctx, workspaceID, path, action, actor)
	return Object{Path: strings.TrimLeft(path, "/"), Size: int64(len(data)), ContentType: contentType}, nil
}

// Get reads a whole object.
func (a *Artifacts) Get(ctx context.Context, workspaceID, path string) ([]byte, string, error) {
	key, err := a.key(workspaceID, path)
	if err != nil {
		return nil, "", err
	}
	rc, info, err := a.Blob.Get(ctx, key)
	if errors.Is(err, blob.ErrNotFound) {
		return nil, "", ErrFileNotFound
	}
	if err != nil {
		return nil, "", err
	}
	defer func() { _ = rc.Close() }()
	data, err := io.ReadAll(rc)
	return data, info.ContentType, err
}

// spoolLimit is SpooledTemporaryFile(max_size=8 MiB).
const spoolLimit = 8 << 20

type spool struct {
	mem  bytes.Buffer
	file *os.File
}

func (s *spool) Write(p []byte) (int, error) {
	if s.file == nil && s.mem.Len()+len(p) > spoolLimit {
		f, err := os.CreateTemp("", "aa-spool-*")
		if err != nil {
			return 0, err
		}
		s.file = f
		if _, err := f.Write(s.mem.Bytes()); err != nil {
			return 0, err
		}
		s.mem.Reset()
	}
	if s.file != nil {
		return s.file.Write(p)
	}
	return s.mem.Write(p)
}

func (s *spool) reader() (io.ReadCloser, error) {
	if s.file == nil {
		return io.NopCloser(bytes.NewReader(s.mem.Bytes())), nil
	}
	if _, err := s.file.Seek(0, io.SeekStart); err != nil {
		s.close()
		return nil, err
	}
	return spoolFile{s.file}, nil
}

func (s *spool) close() {
	if s.file != nil {
		_ = s.file.Close()
		_ = os.Remove(s.file.Name())
	}
}

type spoolFile struct{ *os.File }

func (f spoolFile) Close() error {
	err := f.File.Close()
	_ = os.Remove(f.Name())
	return err
}

// verify copies body into a spool, refusing a length other than size or,
// when want is set, a digest other than want.
func verify(body io.Reader, size int64, want string, fail error) (io.ReadCloser, error) {
	sp := &spool{}
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(sp, h), io.LimitReader(body, size+1))
	if err != nil {
		sp.close()
		return nil, err
	}
	if n != size || (want != "" && hex.EncodeToString(h.Sum(nil)) != want) {
		sp.close()
		return nil, fail
	}
	return sp.reader()
}

// Stream is ArtifactService.stream: the object verified against its size and,
// when it carries one, its sha256 metadata before any byte is returned.
func (a *Artifacts) Stream(ctx context.Context, workspaceID, path string) (Verified, error) {
	key, err := a.key(workspaceID, path)
	if err != nil {
		return Verified{}, err
	}
	rc, info, err := a.Blob.Get(ctx, key)
	if errors.Is(err, blob.ErrNotFound) {
		return Verified{}, ErrFileNotFound
	}
	if err != nil {
		return Verified{}, err
	}
	defer func() { _ = rc.Close() }()
	digest := info.Metadata["sha256"]
	if !isSHA256(digest) {
		digest = ""
	}
	body, err := verify(rc, info.Size, digest, fmt.Errorf("%w: artifact verification failed for %s", ErrIntegrity, domain.PyRepr(path)))
	if err != nil {
		return Verified{}, err
	}
	return Verified{Body: body, ContentType: info.ContentType, Size: info.Size}, nil
}

// Exists is a HEAD.
func (a *Artifacts) Exists(ctx context.Context, workspaceID, path string) (bool, error) {
	key, err := a.key(workspaceID, path)
	if err != nil {
		return false, err
	}
	_, err = a.Blob.Stat(ctx, key)
	if errors.Is(err, blob.ErrNotFound) {
		return false, nil
	}
	return err == nil, err
}

// Head is ArtifactService.head; nil when absent.
func (a *Artifacts) Head(ctx context.Context, workspaceID, path string) (*Head, error) {
	key, err := a.key(workspaceID, path)
	if err != nil {
		return nil, err
	}
	info, err := a.Blob.Stat(ctx, key)
	if errors.Is(err, blob.ErrNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &Head{Size: info.Size, ContentType: info.ContentType, SHA256: info.SHA256}, nil
}

// Delete destroys the object (S3 succeeds for a missing key).
func (a *Artifacts) Delete(ctx context.Context, workspaceID, path string, actor *api.Actor) error {
	key, err := a.key(workspaceID, path)
	if err != nil {
		return err
	}
	if err := a.Blob.Delete(ctx, key); err != nil {
		return err
	}
	a.record(ctx, workspaceID, path, domain.ActionDeleted, actor)
	return nil
}

// Copy is server-side, keeping the metadata; the destination is held to the write bound.
func (a *Artifacts) Copy(ctx context.Context, workspaceID, source, destination string) error {
	src, err := a.key(workspaceID, source)
	if err != nil {
		return err
	}
	dst, err := a.writeKey(workspaceID, destination)
	if err != nil {
		return err
	}
	return a.Blob.Copy(ctx, src, dst, blob.CopyOptions{})
}

// Move copies then deletes; the event lands on the destination.
func (a *Artifacts) Move(ctx context.Context, workspaceID, source, destination string, actor *api.Actor) error {
	src := strings.TrimLeft(source, "/")
	dst := strings.TrimLeft(destination, "/")
	ok, err := a.Exists(ctx, workspaceID, src)
	if err != nil {
		return err
	}
	if !ok {
		return ErrFileNotFound
	}
	if err := a.Copy(ctx, workspaceID, src, dst); err != nil {
		return err
	}
	return a.FinishMove(ctx, workspaceID, src, dst, actor)
}

// FinishMove deletes the copied source and carries its history to the destination.
func (a *Artifacts) FinishMove(ctx context.Context, workspaceID, source, destination string, actor *api.Actor) error {
	src := strings.TrimLeft(source, "/")
	dst := strings.TrimLeft(destination, "/")
	key, err := a.key(workspaceID, src)
	if err != nil {
		return err
	}
	if err := a.Blob.Delete(ctx, key); err != nil {
		return err
	}
	if a.RecordMove != nil {
		a.RecordMove(ctx, workspaceID, src, dst, actor)
	}
	return nil
}

// Discard deletes copies a failed move made; a failure is returned, not hidden.
func (a *Artifacts) Discard(ctx context.Context, workspaceID string, paths []string) error {
	var errs []error
	for _, p := range paths {
		key, err := a.key(workspaceID, p)
		if err == nil {
			err = a.Blob.Delete(ctx, key)
		}
		if err != nil {
			errs = append(errs, fmt.Errorf("discard %s: %w", p, err))
		}
	}
	return errors.Join(errs...)
}

// trashStamp is datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ").
func trashStamp(t time.Time) string {
	t = t.UTC()
	return t.Format("20060102T150405") + fmt.Sprintf(".%06dZ", t.Nanosecond()/1000)
}

// Archive moves the file under .trash/{stamp}/ and returns its new path.
func (a *Artifacts) Archive(ctx context.Context, workspaceID, path string, actor *api.Actor) (string, error) {
	clean := strings.TrimLeft(path, "/")
	ok, err := a.Exists(ctx, workspaceID, clean)
	if err != nil {
		return "", err
	}
	if !ok {
		return "", ErrFileNotFound
	}
	archived := domain.TrashPrefix + trashStamp(a.Now()) + "/" + clean
	key, err := a.key(workspaceID, clean)
	if err != nil {
		return "", err
	}
	dst, err := a.key(workspaceID, archived)
	if err != nil {
		return "", err
	}
	if err := a.Blob.Copy(ctx, key, dst, blob.CopyOptions{}); err != nil {
		return "", err
	}
	if err := a.Blob.Delete(ctx, key); err != nil {
		return "", err
	}
	a.record(ctx, workspaceID, clean, domain.ActionArchived, actor)
	return archived, nil
}

// EnsureNoFileAncestors is ensure_no_file_ancestors.
func (a *Artifacts) EnsureNoFileAncestors(ctx context.Context, workspaceID, path string) error {
	for _, parent := range domain.Parents(path) {
		ok, err := a.Exists(ctx, workspaceID, parent)
		if err != nil {
			return err
		}
		if ok {
			return &domain.ConflictError{Msg: "A file already exists at " + domain.PyRepr(parent)}
		}
	}
	return nil
}

// EnsureWritableFile is ensure_writable_file.
func (a *Artifacts) EnsureWritableFile(ctx context.Context, workspaceID, path string) error {
	if err := a.EnsureNoFileAncestors(ctx, workspaceID, path); err != nil {
		return err
	}
	objs, err := a.List(ctx, workspaceID, path+"/", 1, nil)
	if err != nil {
		return err
	}
	if len(objs) > 0 {
		return &domain.ConflictError{Msg: "A folder already exists at this path"}
	}
	return nil
}

// Restore moves an archived file back to the path it was archived from,
// archiving any file that took that path since.
func (a *Artifacts) Restore(ctx context.Context, workspaceID, archivedPath string, actor *api.Actor) (Restored, error) {
	clean := strings.TrimLeft(archivedPath, "/")
	var parts []string
	if strings.HasPrefix(clean, domain.TrashPrefix) {
		parts = domain.PosixParts(clean)
	}
	original := ""
	if len(parts) > 2 {
		original = strings.Join(parts[2:], "/")
	}
	if original == "" {
		return Restored{}, &InvalidPathError{Msg: "not an archived path: " + domain.PyRepr(archivedPath)}
	}
	if strings.HasSuffix(clean, "/") {
		original += "/"
	}
	ok, err := a.Exists(ctx, workspaceID, clean)
	if err != nil {
		return Restored{}, err
	}
	if !ok {
		return Restored{}, ErrFileNotFound
	}
	if folder, isDir := strings.CutSuffix(original, "/"); isDir {
		if err := a.EnsureNoFileAncestors(ctx, workspaceID, folder); err != nil {
			return Restored{}, err
		}
		taken, err := a.Exists(ctx, workspaceID, folder)
		if err != nil {
			return Restored{}, err
		}
		if taken {
			return Restored{}, &domain.ConflictError{Msg: "A file already exists at " + domain.PyRepr(folder)}
		}
	} else if err := a.EnsureWritableFile(ctx, workspaceID, original); err != nil {
		return Restored{}, err
	}
	var current *string
	taken, err := a.Exists(ctx, workspaceID, original)
	if err != nil {
		return Restored{}, err
	}
	if taken {
		moved, err := a.Archive(ctx, workspaceID, original, actor)
		if err != nil {
			return Restored{}, err
		}
		current = &moved
	}
	src, err := a.key(workspaceID, clean)
	if err != nil {
		return Restored{}, err
	}
	dst, err := a.key(workspaceID, original)
	if err != nil {
		return Restored{}, err
	}
	if err := a.Blob.Copy(ctx, src, dst, blob.CopyOptions{}); err != nil {
		return Restored{}, err
	}
	if err := a.Delete(ctx, workspaceID, clean, actor); err != nil {
		return Restored{}, err
	}
	return Restored{Path: original, RestoredFrom: clean, ArchivedCurrent: current}, nil
}

// pyISO is datetime.isoformat() of an aware UTC time.
func pyISO(t time.Time, zulu bool) string {
	t = t.UTC()
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	if zulu {
		return s + "Z"
	}
	return s + "+00:00"
}

// List is the objects under prefix, at most max of them (0: every one).
// excludeRoots names top-level folders a whole-workspace listing skips
// without walking them.
func (a *Artifacts) List(ctx context.Context, workspaceID, prefix string, max int, excludeRoots []string) ([]Object, error) {
	if len(excludeRoots) > 0 && prefix != "" {
		return nil, errors.New("exclude_roots lists the workspace root; it takes no prefix")
	}
	s, err := a.scope(workspaceID)
	if err != nil {
		return nil, err
	}
	var out []Object
	add := func(info blob.Info) bool {
		if info.Key == "" {
			return false
		}
		o := Object{Path: info.Key, Size: info.Size, ContentType: domain.ContentTypeOf(info.Key)}
		if !info.LastModified.IsZero() {
			lm := pyISO(info.LastModified, false)
			o.LastModified = &lm
		}
		out = append(out, o)
		return max > 0 && len(out) >= max
	}
	subtrees := []string{strings.TrimLeft(prefix, "/")}
	if len(excludeRoots) > 0 {
		objs, folders, err := s.ListDir(ctx, "")
		if err != nil {
			return nil, err
		}
		for _, o := range objs {
			if add(o) {
				return out, nil
			}
		}
		subtrees = subtrees[:0]
		for _, f := range folders {
			if !slices.Contains(excludeRoots, strings.TrimRight(f, "/")) {
				subtrees = append(subtrees, f)
			}
		}
	}
	for _, sub := range subtrees {
		for info, err := range s.List(ctx, sub) {
			if err != nil {
				return nil, pathErr(err)
			}
			if add(info) {
				return out, nil
			}
		}
	}
	return out, nil
}

// PresignedPutURL signs a direct upload; sha256 (hex) is bound as ChecksumSHA256.
func (a *Artifacts) PresignedPutURL(ctx context.Context, workspaceID, path string, opts blob.PutOptions, ttl time.Duration) (blob.Presigned, error) {
	key, err := a.writeKey(workspaceID, path)
	if err != nil {
		return blob.Presigned{}, err
	}
	return a.Blob.PresignPut(ctx, key, opts, ttl)
}

// AuthorizeTTL is authorize_put's expires_in.
const AuthorizeTTL = 600 * time.Second

// AuthorizePut presigns one write bound to its digest twice and records it
// as the actor's write at mint time.
func (a *Artifacts) AuthorizePut(ctx context.Context, workspaceID, path, sha256Hex, contentType string, actor *api.Actor) (blob.Presigned, error) {
	if !isSHA256(sha256Hex) {
		return blob.Presigned{}, &valueError{"sha256 must be a 64-character lowercase hex digest"}
	}
	if contentType == "" {
		contentType = domain.ContentTypeOf(path)
	}
	existed, err := a.Exists(ctx, workspaceID, path)
	if err != nil {
		return blob.Presigned{}, err
	}
	p, err := a.PresignedPutURL(ctx, workspaceID, path, blob.PutOptions{
		ContentType: contentType, SHA256: sha256Hex, Metadata: map[string]string{"sha256": sha256Hex},
	}, AuthorizeTTL)
	if err != nil {
		return blob.Presigned{}, err
	}
	action := domain.ActionCreated
	if existed {
		action = domain.ActionModified
	}
	a.record(ctx, workspaceID, path, action, actor)
	return p, nil
}

// valueError is a ValueError plan_uploads reports per entry.
type valueError struct{ msg string }

func (e *valueError) Error() string { return e.msg }
