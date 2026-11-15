package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// WorkspaceSchemaVersion is WORKSPACE_SCHEMA_VERSION.
const WorkspaceSchemaVersion = 1

// Limits are the task workspace quotas and lease length.
type Limits struct {
	MaxFiles      int
	MaxFileBytes  int64
	MaxTotalBytes int64
	Lease         time.Duration
}

// DefaultLimits are workspace.py's defaults.
func DefaultLimits() Limits {
	return Limits{MaxFiles: 10_000, MaxFileBytes: 256 << 20, MaxTotalBytes: 2 << 30, Lease: time.Hour}
}

// Workspaces is S3WorkspaceRepository over the artifacts bucket.
type Workspaces struct {
	Blob   blob.Store
	Bucket string
	Record func(ctx context.Context, workspaceID, path, action string, actor *api.Actor)
	Now    func() time.Time
	NewHex func() string
	Limits Limits
}

func wsInvalid(format string, a ...any) error {
	return fmt.Errorf("%w: %s", api.ErrWorkspaceInvalid, fmt.Sprintf(format, a...))
}

func wsConflict(format string, a ...any) error {
	return fmt.Errorf("%w: %s", api.ErrWorkspaceConflict, fmt.Sprintf(format, a...))
}

func wsQuota(format string, a ...any) error {
	return fmt.Errorf("%w: %s", api.ErrWorkspaceQuota, fmt.Sprintf(format, a...))
}

// normalize is normalize_workspace_path with the repository's error.
func normalize(p string) (string, error) {
	n, err := domain.NormalizeWorkspacePath(p)
	if err != nil {
		return "", fmt.Errorf("%w: %s", api.ErrWorkspaceInvalid, err.Error())
	}
	return n, nil
}

func identifier(s string) bool {
	return regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`).MatchString(s)
}

type entry struct {
	RelativePath        string `json:"relative_path"`
	ObjectURI           string `json:"object_uri"`
	ObjectVersionOrEtag string `json:"object_version_or_etag"`
	SHA256              string `json:"sha256"`
	Size                int64  `json:"size"`
	ContentType         string `json:"content_type"`
	Mode                int    `json:"mode"`
	Deleted             bool   `json:"deleted"`
}

type manifest struct {
	SchemaVersion  int     `json:"schema_version"`
	WorkspaceID    string  `json:"workspace_id"`
	TaskID         string  `json:"task_id"`
	Generation     int64   `json:"generation"`
	BaseGeneration int64   `json:"base_generation"`
	FencingToken   int64   `json:"fencing_token"`
	Entries        []entry `json:"entries"`
}

type lease struct {
	Owner        string
	FencingToken int64
}

// taskPrefix is task_prefix.
func (w *Workspaces) taskPrefix(workspaceID, taskID string) (string, error) {
	if !identifier(workspaceID) || !identifier(taskID) {
		return "", wsInvalid("workspace_id and task_id must be opaque identifier segments")
	}
	return "workspaces/" + workspaceID + "/tasks/" + taskID, nil
}

func (w *Workspaces) key(workspaceID, taskID, suffix string) (string, error) {
	p, err := w.taskPrefix(workspaceID, taskID)
	if err != nil {
		return "", err
	}
	return p + "/" + strings.TrimLeft(suffix, "/"), nil
}

func (w *Workspaces) uri(key string) string { return "s3://" + w.Bucket + "/" + key }

func (w *Workspaces) validateURI(workspaceID, taskID, raw string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "s3" || u.Host != w.Bucket || u.RawQuery != "" || u.Fragment != "" || strings.Contains(u.Path, ";") {
		return "", wsInvalid("workspace object uses an untrusted bucket")
	}
	key := strings.TrimLeft(u.Path, "/")
	prefix, err := w.taskPrefix(workspaceID, taskID)
	if err != nil {
		return "", err
	}
	if !strings.HasPrefix(key, prefix+"/") || containsString(strings.Split(key, "/"), "..") {
		return "", wsInvalid("workspace object is outside the authenticated task prefix")
	}
	return key, nil
}

func (w *Workspaces) getJSON(ctx context.Context, key string) (map[string]any, []byte, string, bool, error) {
	rc, info, err := w.Blob.Get(ctx, key)
	if errors.Is(err, blob.ErrNotFound) {
		return nil, nil, "", false, nil
	}
	if err != nil {
		return nil, nil, "", false, err
	}
	defer func() { _ = rc.Close() }()
	raw, err := io.ReadAll(rc)
	if err != nil {
		return nil, nil, "", false, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, nil, "", false, err
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, nil, "", false, wsInvalid("JSON object expected at %s", key)
	}
	return m, raw, info.ETag, true, nil
}

func (w *Workspaces) putJSON(ctx context.Context, key string, v any, ifMatch string, ifNoneMatch bool) error {
	body, err := dumpsSorted(v)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(body)
	err = w.Blob.Put(ctx, key, bytes.NewReader(body), int64(len(body)), blob.PutOptions{
		ContentType: "application/json", SHA256: hex.EncodeToString(sum[:]), IfMatch: ifMatch, IfNoneMatch: ifNoneMatch,
	})
	if errors.Is(err, blob.ErrPreconditionFailed) {
		return wsConflict("CAS failed for %s", key)
	}
	return err
}

func identityOf(info blob.Info) string { return info.ETag }

// putImmutable writes a content-addressed body once; an existing object
// must carry the same size and digest.
func (w *Workspaces) putImmutable(ctx context.Context, key string, body io.ReadSeeker, size int64, digest, contentType string) (string, error) {
	err := w.Blob.Put(ctx, key, body, size, blob.PutOptions{
		ContentType: contentType, Metadata: map[string]string{"sha256": digest}, SHA256: digest, IfNoneMatch: true,
	})
	if err != nil && !errors.Is(err, blob.ErrPreconditionFailed) {
		return "", err
	}
	info, serr := w.Blob.Stat(ctx, key)
	if serr != nil {
		return "", serr
	}
	if err != nil && (info.Size != size || info.Metadata["sha256"] != digest) {
		return "", wsConflict("immutable object identity collision at %s", key)
	}
	return identityOf(info), nil
}

func leaseTimestamp(t time.Time) string { return pyISO(t, true) }

func leaseEpoch(v any) float64 {
	switch x := v.(type) {
	case json.Number:
		f, _ := x.Float64()
		return f
	case string:
		t, err := time.Parse(time.RFC3339Nano, x)
		if err != nil {
			return 0
		}
		return float64(t.UnixNano()) / 1e9
	}
	return 0
}

func intOf(v any) int64 {
	switch x := v.(type) {
	case json.Number:
		n, err := x.Int64()
		if err != nil {
			f, _ := x.Float64()
			return int64(f)
		}
		return n
	case bool:
		if x {
			return 1
		}
	}
	return 0
}

func strOf(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case nil:
		return ""
	case json.Number:
		return x.String()
	}
	return fmt.Sprint(v)
}

func (w *Workspaces) now() float64 { return float64(w.Now().UnixNano()) / 1e9 }

func (w *Workspaces) acquireLease(ctx context.Context, workspaceID, taskID, owner string) (lease, error) {
	key, err := w.key(workspaceID, taskID, "lease.json")
	if err != nil {
		return lease{}, err
	}
	now := w.Now()
	cur, _, etag, ok, err := w.getJSON(ctx, key)
	if err != nil {
		return lease{}, err
	}
	expires := leaseTimestamp(now.Add(w.Limits.Lease))
	if !ok {
		if err := w.putJSON(ctx, key, map[string]any{"owner": owner, "fencing_token": 1, "expires_at": expires}, "", true); err != nil {
			return lease{}, err
		}
		return lease{Owner: owner, FencingToken: 1}, nil
	}
	curOwner := strOf(cur["owner"])
	if leaseEpoch(cur["expires_at"]) > w.now() && curOwner != owner {
		return lease{}, wsConflict("task workspace is leased by %s", curOwner)
	}
	token := intOf(cur["fencing_token"]) + 1
	if err := w.putJSON(ctx, key, map[string]any{"owner": owner, "fencing_token": token, "expires_at": expires}, etag, false); err != nil {
		return lease{}, err
	}
	return lease{Owner: owner, FencingToken: token}, nil
}

func (w *Workspaces) assertLease(ctx context.Context, workspaceID, taskID string, l lease) (map[string]any, string, error) {
	key, err := w.key(workspaceID, taskID, "lease.json")
	if err != nil {
		return nil, "", err
	}
	cur, _, etag, ok, err := w.getJSON(ctx, key)
	if err != nil {
		return nil, "", err
	}
	if !ok {
		return nil, "", wsConflict("workspace lease disappeared")
	}
	token := int64(-1)
	if v, has := cur["fencing_token"]; has && v != nil {
		token = intOf(v)
	}
	if strOf(cur["owner"]) != l.Owner || token != l.FencingToken || leaseEpoch(cur["expires_at"]) <= w.now() {
		return nil, "", wsConflict("workspace fencing token is stale")
	}
	return cur, etag, nil
}

func (w *Workspaces) releaseLease(ctx context.Context, workspaceID, taskID string, l lease) {
	cur, etag, err := w.assertLease(ctx, workspaceID, taskID, l)
	if err != nil {
		return
	}
	cur["expires_at"] = leaseTimestamp(time.Unix(0, 0))
	key, _ := w.key(workspaceID, taskID, "lease.json")
	_ = w.putJSON(ctx, key, cur, etag, false)
}

func refFromMap(m map[string]any) (api.ManifestRef, error) {
	for _, k := range []string{"schema_version", "workspace_id", "task_id", "generation", "manifest_uri", "manifest_sha256", "base_generation", "fencing_token"} {
		if _, ok := m[k]; !ok {
			return api.ManifestRef{}, wsInvalid("malformed workspace manifest reference")
		}
	}
	for _, k := range []string{"schema_version", "generation", "base_generation", "fencing_token"} {
		if _, ok := m[k].(json.Number); !ok {
			return api.ManifestRef{}, wsInvalid("malformed workspace manifest reference")
		}
	}
	return api.ManifestRef{
		SchemaVersion: int(intOf(m["schema_version"])), WorkspaceID: strOf(m["workspace_id"]), TaskID: strOf(m["task_id"]),
		Generation: intOf(m["generation"]), ManifestURI: strOf(m["manifest_uri"]), ManifestSHA256: strOf(m["manifest_sha256"]),
		BaseGeneration: intOf(m["base_generation"]), FencingToken: intOf(m["fencing_token"]),
	}, nil
}

func (w *Workspaces) validatedRef(workspaceID, taskID string, ref api.ManifestRef) (api.ManifestRef, error) {
	if ref.SchemaVersion != WorkspaceSchemaVersion || ref.WorkspaceID != workspaceID || ref.TaskID != taskID ||
		ref.Generation < 0 || ref.BaseGeneration < 0 || ref.BaseGeneration > ref.Generation || ref.FencingToken < 0 ||
		!isSHA256(ref.ManifestSHA256) {
		return api.ManifestRef{}, wsInvalid("workspace manifest reference identity is invalid")
	}
	key, err := w.validateURI(workspaceID, taskID, ref.ManifestURI)
	if err != nil {
		return api.ManifestRef{}, err
	}
	want, _ := w.key(workspaceID, taskID, fmt.Sprintf("manifests/%d-%s.json", ref.Generation, ref.ManifestSHA256))
	if key != want {
		return api.ManifestRef{}, wsInvalid("workspace manifest URI does not match its identity")
	}
	return ref, nil
}

func (w *Workspaces) writeManifest(ctx context.Context, workspaceID, taskID string, m manifest) (api.ManifestRef, error) {
	if m.Entries == nil {
		m.Entries = []entry{}
	}
	body, err := dumpsSorted(m)
	if err != nil {
		return api.ManifestRef{}, err
	}
	sum := sha256.Sum256(body)
	digest := hex.EncodeToString(sum[:])
	key, err := w.key(workspaceID, taskID, fmt.Sprintf("manifests/%d-%s.json", m.Generation, digest))
	if err != nil {
		return api.ManifestRef{}, err
	}
	if _, err := w.putImmutable(ctx, key, bytes.NewReader(body), int64(len(body)), digest, "application/json"); err != nil {
		return api.ManifestRef{}, err
	}
	return api.ManifestRef{
		SchemaVersion: WorkspaceSchemaVersion, WorkspaceID: workspaceID, TaskID: taskID, Generation: m.Generation,
		ManifestURI: w.uri(key), ManifestSHA256: digest, BaseGeneration: m.BaseGeneration, FencingToken: m.FencingToken,
	}, nil
}

func (w *Workspaces) initialize(ctx context.Context, workspaceID, taskID string) (api.ManifestRef, error) {
	ref, err := w.writeManifest(ctx, workspaceID, taskID, manifest{SchemaVersion: WorkspaceSchemaVersion, WorkspaceID: workspaceID, TaskID: taskID})
	if err != nil {
		return api.ManifestRef{}, err
	}
	pointer, _ := w.key(workspaceID, taskID, "current.json")
	err = w.putJSON(ctx, pointer, ref, "", true)
	if err == nil {
		return ref, nil
	}
	if !errors.Is(err, api.ErrWorkspaceConflict) {
		return api.ManifestRef{}, err
	}
	cur, _, _, ok, gerr := w.getJSON(ctx, pointer)
	if gerr != nil {
		return api.ManifestRef{}, gerr
	}
	if !ok {
		return api.ManifestRef{}, err
	}
	loaded, err := refFromMap(cur)
	if err != nil {
		return api.ManifestRef{}, err
	}
	return w.validatedRef(workspaceID, taskID, loaded)
}

// CurrentRef is current_manifest_ref, initializing generation 0.
func (w *Workspaces) CurrentRef(ctx context.Context, workspaceID, taskID string) (api.ManifestRef, error) {
	pointer, err := w.key(workspaceID, taskID, "current.json")
	if err != nil {
		return api.ManifestRef{}, err
	}
	cur, _, _, ok, err := w.getJSON(ctx, pointer)
	if err != nil {
		return api.ManifestRef{}, err
	}
	if !ok {
		return w.initialize(ctx, workspaceID, taskID)
	}
	ref, err := refFromMap(cur)
	if err != nil {
		return api.ManifestRef{}, err
	}
	return w.validatedRef(workspaceID, taskID, ref)
}

func (w *Workspaces) snapshot(ctx context.Context, workspaceID, taskID string) (api.ManifestRef, map[string]entry, string, error) {
	pointer, err := w.key(workspaceID, taskID, "current.json")
	if err != nil {
		return api.ManifestRef{}, nil, "", err
	}
	cur, _, etag, ok, err := w.getJSON(ctx, pointer)
	if err != nil {
		return api.ManifestRef{}, nil, "", err
	}
	if !ok {
		if _, err := w.initialize(ctx, workspaceID, taskID); err != nil {
			return api.ManifestRef{}, nil, "", err
		}
		if cur, _, etag, ok, err = w.getJSON(ctx, pointer); err != nil {
			return api.ManifestRef{}, nil, "", err
		}
		if !ok {
			return api.ManifestRef{}, nil, "", wsConflict("workspace current pointer was not created")
		}
	}
	ref, err := refFromMap(cur)
	if err == nil {
		ref, err = w.validatedRef(workspaceID, taskID, ref)
	}
	if err != nil {
		return api.ManifestRef{}, nil, "", err
	}
	entries, err := w.entries(ctx, workspaceID, taskID, ref)
	return ref, entries, etag, err
}

func (w *Workspaces) entries(ctx context.Context, workspaceID, taskID string, ref api.ManifestRef) (map[string]entry, error) {
	ref, err := w.validatedRef(workspaceID, taskID, ref)
	if err != nil {
		return nil, err
	}
	key, err := w.validateURI(workspaceID, taskID, ref.ManifestURI)
	if err != nil {
		return nil, err
	}
	m, raw, _, ok, err := w.getJSON(ctx, key)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, wsInvalid("workspace manifest object is missing")
	}
	sum := sha256.Sum256(raw)
	if hex.EncodeToString(sum[:]) != ref.ManifestSHA256 {
		return nil, wsInvalid("workspace manifest checksum mismatch")
	}
	for _, k := range []string{"schema_version", "workspace_id", "task_id", "generation", "base_generation", "fencing_token"} {
		if _, has := m[k]; !has {
			return nil, wsInvalid("workspace manifest identity is malformed")
		}
	}
	if intOf(m["schema_version"]) != int64(ref.SchemaVersion) || strOf(m["workspace_id"]) != workspaceID || strOf(m["task_id"]) != taskID ||
		intOf(m["generation"]) != ref.Generation || intOf(m["base_generation"]) != ref.BaseGeneration || intOf(m["fencing_token"]) != ref.FencingToken {
		return nil, wsInvalid("workspace manifest identity does not match its ref")
	}
	list, ok := m["entries"].([]any)
	if !ok {
		return nil, wsInvalid("workspace manifest entries must be a list")
	}
	out := map[string]entry{}
	for _, raw := range list {
		em, ok := raw.(map[string]any)
		if !ok {
			return nil, wsInvalid("workspace manifest entry must be an object")
		}
		if _, has := em["relative_path"]; !has {
			return nil, wsInvalid("workspace manifest entry must be an object")
		}
		e := entryFromMap(em)
		if err := w.validateEntry(workspaceID, taskID, e); err != nil {
			return nil, err
		}
		if _, dup := out[e.RelativePath]; dup {
			return nil, wsInvalid("duplicate workspace path: %s", domain.PyRepr(e.RelativePath))
		}
		out[e.RelativePath] = e
	}
	return out, nil
}

func entryFromMap(m map[string]any) entry {
	ct := strOf(m["content_type"])
	if ct == "" {
		ct = "application/octet-stream"
	}
	mode := int(intOf(m["mode"]))
	if mode == 0 {
		mode = 0o644
	}
	deleted, _ := m["deleted"].(bool)
	return entry{
		RelativePath: strOf(m["relative_path"]), ObjectURI: strOf(m["object_uri"]), ObjectVersionOrEtag: strOf(m["object_version_or_etag"]),
		SHA256: strOf(m["sha256"]), Size: intOf(m["size"]), ContentType: ct, Mode: mode, Deleted: deleted,
	}
}

func (w *Workspaces) validateEntry(workspaceID, taskID string, e entry) error {
	if _, err := normalize(e.RelativePath); err != nil {
		return err
	}
	if e.Deleted {
		if e.ObjectURI != "" || e.ObjectVersionOrEtag != "" || e.SHA256 != "" || e.Size != 0 {
			return wsInvalid("workspace tombstone carries object data")
		}
		return nil
	}
	key, err := w.validateURI(workspaceID, taskID, e.ObjectURI)
	if err != nil {
		return err
	}
	if fmt := e.Mode & 0o170000; e.ObjectVersionOrEtag == "" || !isSHA256(e.SHA256) || e.Size < 0 || (fmt != 0 && fmt != 0o100000) {
		return wsInvalid("workspace entry has mutable or invalid object identity")
	}
	want, _ := w.key(workspaceID, taskID, "objects/"+e.SHA256)
	if key != want {
		return wsInvalid("workspace entry object URI does not match its digest")
	}
	return nil
}

func (w *Workspaces) checkQuotas(entries map[string]entry) error {
	var live int
	var total int64
	for _, e := range entries {
		if e.Deleted {
			continue
		}
		live++
		total += e.Size
	}
	if live > w.Limits.MaxFiles {
		return wsQuota("workspace has %d files; limit is %d", live, w.Limits.MaxFiles)
	}
	for _, e := range entries {
		if !e.Deleted && e.Size > w.Limits.MaxFileBytes {
			return wsQuota("workspace file exceeds %d bytes", w.Limits.MaxFileBytes)
		}
	}
	if total > w.Limits.MaxTotalBytes {
		return wsQuota("workspace has %d bytes; limit is %d", total, w.Limits.MaxTotalBytes)
	}
	return nil
}

func (w *Workspaces) commit(ctx context.Context, workspaceID, taskID string, base api.ManifestRef, entries map[string]entry, pointerETag string, l lease) (api.ManifestRef, error) {
	if _, _, err := w.assertLease(ctx, workspaceID, taskID, l); err != nil {
		return api.ManifestRef{}, err
	}
	paths := make([]string, 0, len(entries))
	for p := range entries {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	m := manifest{
		SchemaVersion: WorkspaceSchemaVersion, WorkspaceID: workspaceID, TaskID: taskID,
		Generation: base.Generation + 1, BaseGeneration: base.Generation, FencingToken: l.FencingToken,
	}
	for _, p := range paths {
		m.Entries = append(m.Entries, entries[p])
	}
	next, err := w.writeManifest(ctx, workspaceID, taskID, m)
	if err != nil {
		return api.ManifestRef{}, err
	}
	if _, _, err := w.assertLease(ctx, workspaceID, taskID, l); err != nil {
		return api.ManifestRef{}, err
	}
	pointer, _ := w.key(workspaceID, taskID, "current.json")
	if err := w.putJSON(ctx, pointer, next, pointerETag, false); err != nil {
		return api.ManifestRef{}, err
	}
	return next, nil
}

func (w *Workspaces) record(ctx context.Context, workspaceID, taskID, path, action string, actor *api.Actor) {
	if actor == nil || w.Record == nil {
		return
	}
	w.Record(ctx, workspaceID, "tasks/"+taskID+"/workspace/"+path, action, actor)
}

type change struct{ path, action string }

func (w *Workspaces) owner(o, kind string) string {
	if o != "" {
		return o
	}
	return kind + w.NewHex()
}

// PutFiles is put_files.
func (w *Workspaces) PutFiles(ctx context.Context, workspaceID, taskID string, files []api.WorkspaceFile, opts api.WriteOptions) (api.ManifestRef, error) {
	if len(files) == 0 {
		return w.CurrentRef(ctx, workspaceID, taskID)
	}
	byPath := map[string]api.WorkspaceFile{}
	var order []string
	for _, f := range files {
		p, err := normalize(f.Path)
		if err != nil {
			return api.ManifestRef{}, err
		}
		if int64(len(f.Data)) > w.Limits.MaxFileBytes {
			return api.ManifestRef{}, wsQuota("workspace file %s has %d bytes; limit is %d", domain.PyRepr(p), len(f.Data), w.Limits.MaxFileBytes)
		}
		if _, seen := byPath[p]; !seen {
			order = append(order, p)
		}
		byPath[p] = f
	}
	l, err := w.acquireLease(ctx, workspaceID, taskID, w.owner(opts.Owner, "python-"))
	if err != nil {
		return api.ManifestRef{}, err
	}
	defer w.releaseLease(context.WithoutCancel(ctx), workspaceID, taskID, l)
	ref, entries, pointerETag, err := w.snapshot(ctx, workspaceID, taskID)
	if err != nil {
		return api.ManifestRef{}, err
	}
	same := true
	for _, p := range order {
		sum := sha256.Sum256(byPath[p].Data)
		e, ok := entries[p]
		if !ok || e.Deleted || e.SHA256 != hex.EncodeToString(sum[:]) {
			same = false
			break
		}
	}
	if same {
		return ref, nil
	}
	var changes []change
	for _, p := range order {
		f := byPath[p]
		sum := sha256.Sum256(f.Data)
		digest := hex.EncodeToString(sum[:])
		key, _ := w.key(workspaceID, taskID, "objects/"+digest)
		ct := f.ContentType
		if ct == "" {
			ct = domain.ContentTypeOf(p)
		}
		id, err := w.putImmutable(ctx, key, bytes.NewReader(f.Data), int64(len(f.Data)), digest, ct)
		if err != nil {
			return api.ManifestRef{}, err
		}
		changes = append(changes, change{p, actionFor(entries, p)})
		entries[p] = entry{RelativePath: p, ObjectURI: w.uri(key), ObjectVersionOrEtag: id, SHA256: digest, Size: int64(len(f.Data)), ContentType: ct, Mode: 0o644}
	}
	return w.finish(ctx, workspaceID, taskID, ref, entries, pointerETag, l, changes, opts.Actor)
}

func actionFor(entries map[string]entry, p string) string {
	if e, ok := entries[p]; ok && !e.Deleted {
		return domain.ActionModified
	}
	return domain.ActionCreated
}

func (w *Workspaces) finish(ctx context.Context, workspaceID, taskID string, ref api.ManifestRef, entries map[string]entry, pointerETag string, l lease, changes []change, actor *api.Actor) (api.ManifestRef, error) {
	if err := w.checkQuotas(entries); err != nil {
		return api.ManifestRef{}, err
	}
	next, err := w.commit(ctx, workspaceID, taskID, ref, entries, pointerETag, l)
	if err != nil {
		return api.ManifestRef{}, err
	}
	for _, c := range changes {
		w.record(ctx, workspaceID, taskID, c.path, c.action, actor)
	}
	return next, nil
}

// ImportPrefix is import_workspace_prefix.
func (w *Workspaces) ImportPrefix(ctx context.Context, workspaceID, taskID, sourcePrefix, targetPrefix string, opts api.WriteOptions) (api.ManifestRef, error) {
	if workspaceID == "" || strings.Contains(workspaceID, "/") {
		return api.ManifestRef{}, wsInvalid("workspace_id must be an opaque path segment")
	}
	source := strings.Trim(sourcePrefix, "/")
	if source == "" || containsString(strings.Split(source, "/"), "..") {
		return api.ManifestRef{}, wsInvalid("source prefix is invalid")
	}
	target, err := normalize(targetPrefix)
	if err != nil {
		return api.ManifestRef{}, err
	}
	srcPrefix := "workspaces/" + workspaceID + "/" + source + "/"
	var sources []blob.Info
	for info, err := range w.Blob.List(ctx, srcPrefix) {
		if err != nil {
			return api.ManifestRef{}, err
		}
		sources = append(sources, info)
	}
	if len(sources) > w.Limits.MaxFiles {
		return api.ManifestRef{}, wsQuota("workspace import has %d files; limit is %d", len(sources), w.Limits.MaxFiles)
	}
	var total int64
	for _, s := range sources {
		total += s.Size
	}
	for _, s := range sources {
		if s.Size > w.Limits.MaxFileBytes {
			return api.ManifestRef{}, wsQuota("workspace import file exceeds %d bytes", w.Limits.MaxFileBytes)
		}
	}
	if total > w.Limits.MaxTotalBytes {
		return api.ManifestRef{}, wsQuota("workspace import has %d bytes; limit is %d", total, w.Limits.MaxTotalBytes)
	}
	if len(sources) == 0 {
		return w.CurrentRef(ctx, workspaceID, taskID)
	}
	type item struct {
		info           blob.Info
		relative, path string
	}
	items := make([]item, 0, len(sources))
	seen := map[string]bool{}
	for _, s := range sources {
		rel, err := normalize(s.Key[len(srcPrefix):])
		if err != nil {
			return api.ManifestRef{}, err
		}
		tp, err := normalize(target + "/" + rel)
		if err != nil {
			return api.ManifestRef{}, err
		}
		if seen[tp] {
			return api.ManifestRef{}, wsInvalid("duplicate project path: %s", domain.PyRepr(tp))
		}
		seen[tp] = true
		items = append(items, item{s, rel, tp})
	}
	l, err := w.acquireLease(ctx, workspaceID, taskID, w.owner(opts.Owner, "python-import-"))
	if err != nil {
		return api.ManifestRef{}, err
	}
	defer w.releaseLease(context.WithoutCancel(ctx), workspaceID, taskID, l)
	ref, entries, pointerETag, err := w.snapshot(ctx, workspaceID, taskID)
	if err != nil {
		return api.ManifestRef{}, err
	}
	var changes []change
	for _, it := range items {
		e, err := w.importOne(ctx, workspaceID, taskID, it.info, it.relative)
		if err != nil {
			return api.ManifestRef{}, err
		}
		e.RelativePath = it.path
		changes = append(changes, change{it.path, actionFor(entries, it.path)})
		entries[it.path] = e
	}
	return w.finish(ctx, workspaceID, taskID, ref, entries, pointerETag, l, changes, opts.Actor)
}

func (w *Workspaces) importOne(ctx context.Context, workspaceID, taskID string, src blob.Info, relative string) (entry, error) {
	rc, info, err := w.Blob.Get(ctx, src.Key)
	if err != nil {
		return entry{}, err
	}
	sp := &spool{}
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(sp, h), rc)
	_ = rc.Close()
	if err != nil {
		sp.close()
		return entry{}, err
	}
	if n != src.Size {
		sp.close()
		return entry{}, wsInvalid("source object size changed during import: %s", domain.PyRepr(relative))
	}
	body, err := sp.reader()
	if err != nil {
		return entry{}, err
	}
	defer func() { _ = body.Close() }()
	data, err := io.ReadAll(body)
	if err != nil {
		return entry{}, err
	}
	digest := hex.EncodeToString(h.Sum(nil))
	ct := info.ContentType
	if ct == "" {
		ct = domain.ContentTypeOf(relative)
	}
	key, _ := w.key(workspaceID, taskID, "objects/"+digest)
	id, err := w.putImmutable(ctx, key, bytes.NewReader(data), n, digest, ct)
	if err != nil {
		return entry{}, err
	}
	return entry{ObjectURI: w.uri(key), ObjectVersionOrEtag: id, SHA256: digest, Size: n, ContentType: ct, Mode: 0o644}, nil
}

// AttachObject is attach_object.
func (w *Workspaces) AttachObject(ctx context.Context, workspaceID, taskID, path string, src api.AttachSource, opts api.WriteOptions) (api.ManifestRef, error) {
	clean, err := normalize(path)
	if err != nil {
		return api.ManifestRef{}, err
	}
	if !isSHA256(src.SHA256) {
		return api.ManifestRef{}, wsInvalid("attach expected_sha256 is not a lowercase hex digest")
	}
	if src.Size < 0 {
		return api.ManifestRef{}, wsInvalid("attach expected_size must be a non-negative integer")
	}
	if src.ContentType == "" {
		return api.ManifestRef{}, wsInvalid("attach content_type is required")
	}
	if !identifier(workspaceID) {
		return api.ManifestRef{}, wsInvalid("workspace_id must be an opaque identifier segment")
	}
	source := strings.Trim(src.Key, "/")
	if source == "" || containsString(strings.Split(source, "/"), "..") {
		return api.ManifestRef{}, wsInvalid("attach source key is invalid")
	}
	sourceKey := "workspaces/" + workspaceID + "/" + source
	dest, err := w.key(workspaceID, taskID, "objects/"+src.SHA256)
	if err != nil {
		return api.ManifestRef{}, err
	}
	head, err := w.Blob.Stat(ctx, sourceKey)
	if errors.Is(err, blob.ErrNotFound) {
		return api.ManifestRef{}, wsInvalid("attach source object is missing: %s", domain.PyRepr(source))
	}
	if err != nil {
		return api.ManifestRef{}, err
	}
	if head.SHA256 != src.SHA256 || head.Size != src.Size {
		return api.ManifestRef{}, wsInvalid("attach source identity does not match the declared sha256/size")
	}
	if src.Size > w.Limits.MaxFileBytes {
		return api.ManifestRef{}, wsQuota("attach file has %d bytes; limit is %d", src.Size, w.Limits.MaxFileBytes)
	}
	var id string
	existing, err := w.Blob.Stat(ctx, dest)
	switch {
	case err == nil:
		if existing.Size != src.Size || existing.Metadata["sha256"] != src.SHA256 {
			return api.ManifestRef{}, wsConflict("immutable object identity collision at %s", dest)
		}
		id = identityOf(existing)
	case errors.Is(err, blob.ErrNotFound):
		if err := w.Blob.Copy(ctx, sourceKey, dest, blob.CopyOptions{Replace: true, ContentType: src.ContentType, Metadata: map[string]string{"sha256": src.SHA256}}); err != nil {
			return api.ManifestRef{}, err
		}
		after, err := w.Blob.Stat(ctx, dest)
		if err != nil {
			return api.ManifestRef{}, err
		}
		id = identityOf(after)
	default:
		return api.ManifestRef{}, err
	}
	l, err := w.acquireLease(ctx, workspaceID, taskID, w.owner(opts.Owner, "python-attach-"))
	if err != nil {
		return api.ManifestRef{}, err
	}
	defer w.releaseLease(context.WithoutCancel(ctx), workspaceID, taskID, l)
	ref, entries, pointerETag, err := w.snapshot(ctx, workspaceID, taskID)
	if err != nil {
		return api.ManifestRef{}, err
	}
	if e, ok := entries[clean]; ok && !e.Deleted && e.SHA256 == src.SHA256 {
		return ref, nil
	}
	changes := []change{{clean, actionFor(entries, clean)}}
	entries[clean] = entry{RelativePath: clean, ObjectURI: w.uri(dest), ObjectVersionOrEtag: id, SHA256: src.SHA256, Size: src.Size, ContentType: src.ContentType, Mode: 0o644}
	return w.finish(ctx, workspaceID, taskID, ref, entries, pointerETag, l, changes, opts.Actor)
}

func (w *Workspaces) entry(ctx context.Context, workspaceID, taskID, path string) (entry, error) {
	clean, err := normalize(path)
	if err != nil {
		return entry{}, err
	}
	_, entries, _, err := w.snapshot(ctx, workspaceID, taskID)
	if err != nil {
		return entry{}, err
	}
	e, ok := entries[clean]
	if !ok || e.Deleted {
		return entry{}, ErrFileNotFound
	}
	return e, nil
}

// open reads an entry's object by its recorded identity.
func (w *Workspaces) open(ctx context.Context, workspaceID, taskID string, e entry) (io.ReadCloser, blob.Info, error) {
	key, err := w.validateURI(workspaceID, taskID, e.ObjectURI)
	if err != nil {
		return nil, blob.Info{}, err
	}
	rc, info, err := w.Blob.Get(ctx, key)
	if errors.Is(err, blob.ErrNotFound) {
		return nil, blob.Info{}, wsInvalid("workspace object identity is unavailable for %s", domain.PyRepr(e.RelativePath))
	}
	if err != nil {
		return nil, blob.Info{}, err
	}
	if !strings.HasPrefix(e.ObjectVersionOrEtag, "version:") && e.ObjectVersionOrEtag != "" && info.ETag != e.ObjectVersionOrEtag {
		_ = rc.Close()
		return nil, blob.Info{}, wsInvalid("workspace object identity is unavailable for %s", domain.PyRepr(e.RelativePath))
	}
	return rc, info, nil
}

// Stream is the verified stream of a committed file.
func (w *Workspaces) Stream(ctx context.Context, workspaceID, taskID, path string) (Verified, error) {
	e, err := w.entry(ctx, workspaceID, taskID, path)
	if err != nil {
		return Verified{}, err
	}
	rc, info, err := w.open(ctx, workspaceID, taskID, e)
	if err != nil {
		return Verified{}, err
	}
	defer func() { _ = rc.Close() }()
	fail := wsInvalid("workspace object verification failed for %s", domain.PyRepr(e.RelativePath))
	if info.Size != e.Size {
		return Verified{}, fail
	}
	body, err := verify(rc, e.Size, e.SHA256, fail)
	if err != nil {
		return Verified{}, err
	}
	return Verified{Body: body, ContentType: e.ContentType, Size: e.Size}, nil
}

// Get reads a committed file whole.
func (w *Workspaces) Get(ctx context.Context, workspaceID, taskID, path string) ([]byte, string, error) {
	v, err := w.Stream(ctx, workspaceID, taskID, path)
	if err != nil {
		return nil, "", err
	}
	defer func() { _ = v.Body.Close() }()
	data, err := io.ReadAll(v.Body)
	return data, v.ContentType, err
}

// Exists reports a live entry.
func (w *Workspaces) Exists(ctx context.Context, workspaceID, taskID, path string) (bool, error) {
	_, err := w.entry(ctx, workspaceID, taskID, path)
	if errors.Is(err, ErrFileNotFound) {
		return false, nil
	}
	return err == nil, err
}

// GetObjectRef is get_object_ref: a verified task object read by its
// reference, without manifest membership (execution stdout/stderr).
func (w *Workspaces) GetObjectRef(ctx context.Context, workspaceID, taskID string, ref map[string]any) ([]byte, error) {
	if _, ok := ref["relative_path"]; !ok {
		return nil, wsInvalid("malformed workspace object reference")
	}
	e := entryFromMap(ref)
	size, hasSize := ref["size"]
	if !hasSize || size == nil {
		size = json.Number("0")
	}
	n, isNum := size.(json.Number)
	sz, nerr := n.Int64()
	if !isNum || nerr != nil || sz < 0 || sz > w.Limits.MaxFileBytes || e.Deleted || !isSHA256(e.SHA256) || e.ObjectVersionOrEtag == "" {
		return nil, wsInvalid("workspace object reference identity is invalid")
	}
	e.Size = sz
	if _, err := normalize(e.RelativePath); err != nil {
		return nil, err
	}
	key, err := w.validateURI(workspaceID, taskID, e.ObjectURI)
	if err != nil {
		return nil, err
	}
	if want, _ := w.key(workspaceID, taskID, "objects/"+e.SHA256); key != want {
		return nil, wsInvalid("workspace object URI does not match its sha256")
	}
	if e.ObjectVersionOrEtag == "version:" {
		return nil, wsInvalid("workspace object version is empty")
	}
	rc, _, err := w.open(ctx, workspaceID, taskID, e)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rc.Close() }()
	data, err := io.ReadAll(io.LimitReader(rc, e.Size+1))
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(data)
	if int64(len(data)) != e.Size || hex.EncodeToString(sum[:]) != e.SHA256 {
		return nil, wsInvalid("workspace object verification failed for %s", domain.PyRepr(e.RelativePath))
	}
	return data, nil
}
