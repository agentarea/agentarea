package service

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// MaxListedFiles is MAX_LISTED_FILES.
const MaxListedFiles = 10_000

// MaxAttachmentBytes is DEFAULT_MAX_FILE_BYTES, the presigned attachment cap.
const MaxAttachmentBytes = 256 * 1024 * 1024

// AttachmentTTL is the staging upload URL's expiry.
const AttachmentTTL = 3600 * time.Second

// HTTPError is an HTTPException the routes raise: status and detail.
type HTTPError struct {
	Status int
	Detail string
}

func (e *HTTPError) Error() string { return e.Detail }

func httpErr(status int, detail string) error { return &HTTPError{Status: status, Detail: detail} }

func notFound() error { return httpErr(http.StatusNotFound, "File not found") }

func randomHex() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return hex.EncodeToString(b[:])
}

func userActor(userID string) *api.Actor {
	return &api.Actor{UserID: userID, ActorType: domain.ActorUser}
}

// recordEvent is DbArtifactEventRecorder.record behind ArtifactService._record:
// its own short transaction, a failure logged and swallowed.
func (s *Service) recordEvent(ctx context.Context, workspaceID, path, action string, actor *api.Actor) {
	err := func() error {
		if s.d.Events == nil || s.d.DB == nil {
			return errors.New("no artifact event store")
		}
		ws, err := workspaceScope(workspaceID)
		if err != nil {
			return err
		}
		actorType := actor.ActorType
		if actorType == "" {
			actorType = domain.ActorUser
		}
		return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			return s.d.Events.Insert(ctx, sess, domain.ArtifactEvent{
				Path: strings.TrimLeft(path, "/"), Action: action, ActorType: actorType, CreatedBy: actor.UserID,
				AgentID: actor.AgentID, TaskID: actor.TaskID, CreatedAt: s.d.Now(),
			})
		})
	}()
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to record artifact event", "action", action, "path", path, "workspace", workspaceID, "error", err)
	}
}

// recordMove carries source's events onto destination and, with an actor,
// appends the move, in one transaction; a failure is logged.
func (s *Service) recordMove(ctx context.Context, workspaceID, source, destination string, actor *api.Actor) {
	err := func() error {
		if s.d.Events == nil || s.d.DB == nil {
			return errors.New("no artifact event store")
		}
		ws, err := workspaceScope(workspaceID)
		if err != nil {
			return err
		}
		return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			now := s.d.Now()
			if err := s.d.Events.Rename(ctx, sess, source, destination, now); err != nil {
				return err
			}
			if actor == nil {
				return nil
			}
			actorType := actor.ActorType
			if actorType == "" {
				actorType = domain.ActorUser
			}
			return s.d.Events.Insert(ctx, sess, domain.ArtifactEvent{
				Path: destination, Action: domain.ActionMoved, ActorType: actorType, CreatedBy: actor.UserID,
				AgentID: actor.AgentID, TaskID: actor.TaskID, CreatedAt: now,
			})
		})
	}()
	if err != nil {
		s.d.Log.ErrorContext(ctx, "Failed to record artifact move", "source", source, "destination", destination, "workspace", workspaceID, "error", err)
	}
}

// Listing is WorkspaceFileListResponse.
type Listing struct {
	Files       []Object
	Directories []string
	Truncated   bool
}

func (s *Service) projectIDs(ctx context.Context, ws scope.Workspace) ([]string, error) {
	if s.d.Projects == nil {
		return nil, errors.New("listing workspace files needs the projects lookup")
	}
	return s.d.Projects.IDs(ctx, ws)
}

func reservedRoots() []string { return []string{"tasks", "staging", "events", ".trash"} }

// ListWorkspace is list_workspace_files.
func (s *Service) ListWorkspace(ctx context.Context, ws scope.Workspace) (Listing, error) {
	objs, err := s.art.List(ctx, ws.ID(), "", MaxListedFiles+1, reservedRoots())
	if err != nil {
		return Listing{}, err
	}
	out := Listing{Files: []Object{}, Truncated: len(objs) > MaxListedFiles}
	if out.Truncated {
		objs = objs[:MaxListedFiles]
	}
	dirs := map[string]bool{}
	for _, o := range objs {
		if domain.IsReservedPath(o.Path) {
			continue
		}
		if strings.HasSuffix(o.Path, "/") {
			dirs[o.Path] = true
			continue
		}
		out.Files = append(out.Files, o)
	}
	ids, err := s.projectIDs(ctx, ws)
	if err != nil {
		return Listing{}, err
	}
	for _, id := range ids {
		dirs["projects/"+id+"/"] = true
	}
	out.Directories = make([]string, 0, len(dirs))
	for d := range dirs {
		out.Directories = append(out.Directories, d)
	}
	sort.Strings(out.Directories)
	return out, nil
}

// resolveUpload is _resolve_upload_path: 403 for apps/, 422 otherwise.
func resolveUpload(p, filename string) (string, error) {
	r, err := domain.ResolveWritePath(p, filename)
	var ro *domain.ReadOnlyError
	switch {
	case errors.As(err, &ro):
		return "", httpErr(http.StatusForbidden, err.Error())
	case err != nil:
		return "", httpErr(http.StatusUnprocessableEntity, err.Error())
	}
	return r, nil
}

func conflict(err error) error {
	var c *domain.ConflictError
	if errors.As(err, &c) {
		return httpErr(http.StatusConflict, c.Msg)
	}
	return err
}

// CreateDirectory is create_workspace_directory.
func (s *Service) CreateDirectory(ctx context.Context, ws scope.Workspace, userID, requested string) (string, error) {
	requested = strings.TrimSuffix(requested, "/")
	if requested == "" {
		return "", httpErr(http.StatusUnprocessableEntity, "Folder path must not be empty")
	}
	p, err := resolveUpload(requested, "")
	if err != nil {
		return "", err
	}
	dir := p + "/"
	if err := s.art.EnsureNoFileAncestors(ctx, ws.ID(), p); err != nil {
		return "", conflict(err)
	}
	exists, err := s.art.Exists(ctx, ws.ID(), p)
	if err != nil {
		return "", err
	}
	if exists {
		return "", httpErr(http.StatusConflict, "A file already exists at "+domain.PyRepr(p))
	}
	ids, err := s.projectIDs(ctx, ws)
	if err != nil {
		return "", err
	}
	for _, id := range ids {
		if strings.HasPrefix("projects/"+id+"/", dir) {
			return "", httpErr(http.StatusConflict, "A folder already exists at this path")
		}
	}
	objs, err := s.art.List(ctx, ws.ID(), dir, 1, nil)
	if err != nil {
		return "", err
	}
	if len(objs) > 0 {
		return "", httpErr(http.StatusConflict, "A folder already exists at this path")
	}
	if _, err := s.art.Put(ctx, ws.ID(), dir, nil, "application/x-directory", userActor(userID)); err != nil {
		return "", err
	}
	return dir, nil
}

// PresignedAttachment is PresignUploadResponse.
type PresignedAttachment struct {
	Ref, UploadURL string
	ExpiresIn      int
}

// PresignAttachment is create_attachment_upload_url.
func (s *Service) PresignAttachment(ctx context.Context, ws scope.Workspace, filename, contentType, sha256Hex string, size int64) (PresignedAttachment, error) {
	if !isSHA256(sha256Hex) {
		return PresignedAttachment{}, httpErr(http.StatusUnprocessableEntity, "sha256 must be a 64-character lowercase hex digest")
	}
	if size < 0 {
		return PresignedAttachment{}, httpErr(http.StatusUnprocessableEntity, "size must be a non-negative integer")
	}
	if size > MaxAttachmentBytes {
		return PresignedAttachment{}, httpErr(http.StatusRequestEntityTooLarge, fmt.Sprintf("attachment exceeds the %d-byte per-file limit", MaxAttachmentBytes))
	}
	name := domain.PosixName(filename)
	if name == "" {
		name = "unnamed"
	}
	ref := "staging/" + s.d.NewHex() + "/" + name
	p, err := s.art.PresignedPutURL(ctx, ws.ID(), ref, blob.PutOptions{ContentType: contentType, SHA256: sha256Hex}, AttachmentTTL)
	if err != nil {
		return PresignedAttachment{}, err
	}
	return PresignedAttachment{Ref: ref, UploadURL: p.URL, ExpiresIn: int(AttachmentTTL / time.Second)}, nil
}

// PlanUploads is plan_uploads with the caller recorded as each write's actor.
func (s *Service) PlanUploads(ctx context.Context, ws scope.Workspace, actorUserID string, entries []api.UploadEntry) ([]api.PlannedUpload, error) {
	out := make([]api.PlannedUpload, 0, len(entries))
	for _, e := range entries {
		p, err := s.planOne(ctx, ws.ID(), userActor(actorUserID), e)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}

func planError(path, msg string) api.PlannedUpload {
	return api.PlannedUpload{Path: path, Status: "error", Error: &msg}
}

func (s *Service) planOne(ctx context.Context, workspaceID string, actor *api.Actor, e api.UploadEntry) (api.PlannedUpload, error) {
	if e.Path == "" {
		return planError(e.Path, "path is required"), nil
	}
	resolved, err := domain.ResolveWritePath(e.Path, "")
	if err == nil {
		var head *Head
		head, err = s.art.Head(ctx, workspaceID, resolved)
		if err == nil && head != nil && head.SHA256 == e.SHA256 {
			return api.PlannedUpload{Path: resolved, Status: "unchanged"}, nil
		}
	}
	if err == nil {
		err = s.art.EnsureWritableFile(ctx, workspaceID, resolved)
	}
	ct := ""
	if e.ContentType != nil {
		ct = *e.ContentType
	}
	var put blob.Presigned
	if err == nil {
		put, err = s.art.AuthorizePut(ctx, workspaceID, resolved, e.SHA256, ct, actor)
	}
	if err != nil {
		var ve *valueError
		var ip *InvalidPathError
		if domain.IsWorkspaceError(err) || errors.As(err, &ve) || errors.As(err, &ip) {
			return planError(e.Path, err.Error()), nil
		}
		return api.PlannedUpload{}, err
	}
	if ct == "" {
		ct = domain.ContentTypeOf(resolved)
	}
	sum, _ := hex.DecodeString(e.SHA256)
	method := http.MethodPut
	ttl := int(AuthorizeTTL / time.Second)
	return api.PlannedUpload{
		Path: resolved, Status: "upload", UploadURL: &put.URL, Method: &method, ExpiresIn: &ttl,
		Headers: map[string]string{
			"Content-Type":          ct,
			"x-amz-checksum-sha256": base64.StdEncoding.EncodeToString(sum),
			"x-amz-meta-sha256":     e.SHA256,
		},
	}, nil
}

// Moved is MovedFileResponse.
type Moved struct {
	Source, Destination string
	Count               int
}

// Move is move_workspace_file.
func (s *Service) Move(ctx context.Context, ws scope.Workspace, userID, source, destination string) (Moved, error) {
	src, err := resolveUpload(strings.TrimSuffix(source, "/"), "")
	if err != nil {
		return Moved{}, err
	}
	dst, err := resolveUpload(strings.TrimSuffix(destination, "/"), "")
	if err != nil {
		return Moved{}, err
	}
	if src == dst {
		return Moved{}, httpErr(http.StatusUnprocessableEntity, "Source and destination are the same")
	}
	if strings.HasPrefix(dst, src+"/") {
		return Moved{}, httpErr(http.StatusUnprocessableEntity, "Cannot move a folder into itself")
	}
	wid, actor := ws.ID(), userActor(userID)
	if err := s.art.EnsureNoFileAncestors(ctx, wid, dst); err != nil {
		return Moved{}, conflict(err)
	}
	taken, err := s.art.Exists(ctx, wid, dst)
	if err != nil {
		return Moved{}, err
	}
	if taken {
		return Moved{}, httpErr(http.StatusConflict, "A file already exists at "+domain.PyRepr(dst))
	}
	under, err := s.art.List(ctx, wid, dst+"/", 1, nil)
	if err != nil {
		return Moved{}, err
	}
	if len(under) > 0 {
		return Moved{}, httpErr(http.StatusConflict, "A folder already exists at this path")
	}
	single, err := s.art.Exists(ctx, wid, src)
	if err != nil {
		return Moved{}, err
	}
	if single {
		if err := s.art.Move(ctx, wid, src, dst, actor); err != nil {
			return Moved{}, err
		}
		return Moved{Source: src, Destination: dst, Count: 1}, nil
	}
	contents, err := s.art.List(ctx, wid, src+"/", 0, nil)
	if err != nil {
		return Moved{}, err
	}
	if len(contents) == 0 {
		return Moved{}, notFound()
	}
	type move struct{ from, to string }
	moves := make([]move, len(contents))
	for i, o := range contents {
		moves[i] = move{o.Path, dst + "/" + o.Path[len(src)+1:]}
	}
	for _, m := range moves {
		if _, err := resolveUpload(strings.TrimSuffix(m.to, "/"), ""); err != nil {
			return Moved{}, err
		}
	}
	copied := make([]string, 0, len(moves))
	for _, m := range moves {
		if err := s.art.Copy(ctx, wid, m.from, m.to); err != nil {
			if derr := s.art.Discard(context.WithoutCancel(ctx), wid, copied); derr != nil {
				s.d.Log.ErrorContext(ctx, "Failed to discard copies of an aborted folder move", "source", src, "destination", dst, "workspace", wid, "error", derr)
			}
			return Moved{}, err
		}
		copied = append(copied, m.to)
	}
	for _, m := range moves {
		if err := s.art.FinishMove(ctx, wid, m.from, m.to, actor); err != nil {
			return Moved{}, err
		}
	}
	return Moved{Source: src, Destination: dst, Count: len(moves)}, nil
}

// Archive is delete_workspace_file: the file goes to .trash/.
func (s *Service) Archive(ctx context.Context, ws scope.Workspace, userID, filePath string) (string, string, error) {
	clean := strings.TrimLeft(filePath, "/")
	if domain.IsReservedPath(clean) {
		return "", "", httpErr(http.StatusBadRequest, domain.PyRepr(clean)+" is not a workspace library file")
	}
	if err := domain.EnsureNotReadOnly(clean); err != nil {
		return "", "", httpErr(http.StatusForbidden, err.Error())
	}
	exists, err := s.art.Exists(ctx, ws.ID(), clean)
	var ip *InvalidPathError
	if errors.As(err, &ip) {
		exists, err = false, nil
	}
	if err != nil {
		return "", "", err
	}
	if !exists {
		return "", "", notFound()
	}
	archived, err := s.art.Archive(ctx, ws.ID(), clean, userActor(userID))
	return clean, archived, err
}

// Restore is restore_workspace_file.
func (s *Service) Restore(ctx context.Context, ws scope.Workspace, userID, filePath string) (Restored, error) {
	clean := strings.TrimLeft(filePath, "/")
	if !strings.HasPrefix(clean, domain.TrashPrefix) {
		return Restored{}, httpErr(http.StatusBadRequest, "Not an archived file")
	}
	parts := domain.PosixParts(clean)
	original := ""
	if len(parts) > 2 {
		original = strings.Join(parts[2:], "/")
	}
	if err := domain.EnsureNotReadOnly(original); err != nil {
		return Restored{}, httpErr(http.StatusForbidden, err.Error())
	}
	r, err := s.art.Restore(ctx, ws.ID(), clean, userActor(userID))
	var ip *InvalidPathError
	switch {
	case errors.Is(err, ErrFileNotFound), errors.As(err, &ip):
		return Restored{}, notFound()
	case err != nil:
		return Restored{}, conflict(err)
	}
	return r, nil
}

// History is workspace_file_history.
func (s *Service) History(ctx context.Context, ws scope.Workspace, path string) (string, []domain.ArtifactEvent, error) {
	clean := strings.TrimLeft(path, "/")
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return "", nil, err
	}
	defer release()
	evs, err := s.d.Events.History(ctx, sess, clean)
	return clean, evs, err
}

// EventTime is utc_isoformat of a naive column value.
func EventTime(t time.Time) string {
	return pyISO(time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.UTC), true)
}

// Download is stream_workspace_file: a verified body, or 404 for anything
// that cannot be served.
func (s *Service) Download(ctx context.Context, ws scope.Workspace, filePath string) (Verified, error) {
	taskID, rel, isTask, err := domain.TaskWorkspacePath(filePath)
	var v Verified
	switch {
	case err != nil:
	case isTask:
		v, err = s.ws.Stream(ctx, ws.ID(), taskID, rel)
	case domain.IsReservedPath(filePath):
		err = ErrFileNotFound
	default:
		v, err = s.art.Stream(ctx, ws.ID(), filePath)
	}
	var ip *InvalidPathError
	if errors.Is(err, ErrFileNotFound) || errors.Is(err, ErrIntegrity) || errors.As(err, &ip) || domain.IsValidation(err) || errors.Is(err, api.ErrWorkspaceInvalid) {
		return Verified{}, notFound()
	}
	return v, err
}

// FileURL is download_workspace_file: the API URL that streams the file.
func (s *Service) FileURL(ctx context.Context, ws scope.Workspace, filePath string) (string, error) {
	taskID, rel, isTask, err := domain.TaskWorkspacePath(filePath)
	exists := false
	switch {
	case err != nil:
	case isTask:
		exists, err = s.ws.Exists(ctx, ws.ID(), taskID, rel)
	case domain.IsReservedPath(filePath):
	default:
		exists, err = s.art.Exists(ctx, ws.ID(), filePath)
	}
	var ip *InvalidPathError
	if errors.As(err, &ip) || domain.IsValidation(err) || errors.Is(err, api.ErrWorkspaceInvalid) {
		exists, err = false, nil
	}
	if err != nil {
		return "", err
	}
	if !exists {
		return "", notFound()
	}
	return strings.TrimRight(s.d.APIURL, "/") + "/v1/workspaces/" + ws.Slug() + "/files/download/" + QuotePath(strings.TrimLeft(filePath, "/")), nil
}

// Files is api.Files over the artifact store, for the project routes.
func (s *Service) Files() api.Files { return filesAPI{s} }

type filesAPI struct{ s *Service }

func apiErr(err error) error {
	var ip *InvalidPathError
	if errors.As(err, &ip) {
		return fmt.Errorf("%w: %s", api.ErrInvalidPath, ip.Msg)
	}
	return err
}

func (f filesAPI) PlanUploads(ctx context.Context, ws scope.Workspace, actorUserID string, entries []api.UploadEntry) ([]api.PlannedUpload, error) {
	return f.s.PlanUploads(ctx, ws, actorUserID, entries)
}

func (f filesAPI) List(ctx context.Context, ws scope.Workspace, prefix string) ([]api.FileInfo, error) {
	objs, err := f.s.art.List(ctx, ws.ID(), prefix, 1000, nil)
	if err != nil {
		return nil, apiErr(err)
	}
	out := make([]api.FileInfo, len(objs))
	for i, o := range objs {
		out[i] = api.FileInfo{Path: o.Path, Size: o.Size, LastModified: o.LastModified}
	}
	return out, nil
}

func (f filesAPI) Get(ctx context.Context, ws scope.Workspace, path string) (api.File, error) {
	data, ct, err := f.s.art.Get(ctx, ws.ID(), path)
	if err != nil {
		return api.File{}, apiErr(err)
	}
	return api.File{Data: data, ContentType: ct}, nil
}

func (f filesAPI) Exists(ctx context.Context, ws scope.Workspace, path string) (bool, error) {
	ok, err := f.s.art.Exists(ctx, ws.ID(), path)
	return ok, apiErr(err)
}

func (f filesAPI) Head(ctx context.Context, ws scope.Workspace, path string) (api.ObjectHead, bool, error) {
	h, err := f.s.art.Head(ctx, ws.ID(), path)
	if err != nil || h == nil {
		return api.ObjectHead{}, false, apiErr(err)
	}
	return api.ObjectHead{SHA256: h.SHA256, Size: h.Size, ContentType: h.ContentType}, true, nil
}

func (f filesAPI) Delete(ctx context.Context, ws scope.Workspace, actorUserID, path string) error {
	return apiErr(f.s.art.Delete(ctx, ws.ID(), path, userActor(actorUserID)))
}

func (filesAPI) DownloadHeaders(contentType, filename string) http.Header {
	return DownloadHeaders(contentType, filename, "file.bin")
}

func containsString(xs []string, x string) bool { return slices.Contains(xs, x) }
