package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// httpx's timeout applies to each connect, read and write, not to the whole
// exchange: a long download that keeps moving is never cut.
const (
	taskFileRequestIdle = 30 * time.Second
	taskFileStreamIdle  = 300 * time.Second
)

// TaskFiles is api.TaskFiles over the sandbox manager and the harness bucket.
func (s *Service) TaskFiles() api.TaskFiles { return taskFiles{s} }

type taskFiles struct{ s *Service }

func taskQuery(workspaceID, taskID string) url.Values {
	return url.Values{"workspace_id": {workspaceID}, "task_id": {taskID}}
}

func (t taskFiles) Artifacts(ctx context.Context, workspaceID, taskID string) ([]api.TaskArtifact, error) {
	raw, err := t.fetch(ctx, "/sandbox/artifacts", taskQuery(workspaceID, taskID), "Artifact list")
	if err != nil {
		return nil, err
	}
	items, err := parseArtifactList(raw)
	if err != nil {
		t.s.d.Log.ErrorContext(ctx, "Sandbox manager returned an invalid artifact list", "error", err)
		return nil, api.ErrArtifactListInvalid
	}
	return items, nil
}

func (t taskFiles) Artifact(ctx context.Context, workspaceID, taskID, artifactID string) (api.Download, error) {
	return t.download(ctx, "/sandbox/artifacts/"+url.PathEscape(artifactID), taskQuery(workspaceID, taskID),
		"Artifact", artifactID, "application/octet-stream")
}

func (t taskFiles) ListFiles(ctx context.Context, workspaceID, taskID, prefix string, harness bool) ([]string, error) {
	if harness {
		return t.harnessList(ctx, workspaceID, taskID, prefix)
	}
	q := taskQuery(workspaceID, taskID)
	q.Set("list", prefix)
	q.Set("ensure", "false")
	raw, err := t.fetch(ctx, "/sandbox/files", q, "Sandbox workspace")
	if err != nil {
		return nil, err
	}
	paths, err := parsePathList(raw)
	if err != nil {
		t.s.d.Log.ErrorContext(ctx, "Sandbox manager returned an invalid file list", "error", err)
		return nil, api.ErrSandboxFileListInvalid
	}
	return paths, nil
}

func (t taskFiles) ReadFile(ctx context.Context, workspaceID, taskID, p string, harness bool) (api.Download, error) {
	if harness {
		return t.harnessGet(ctx, workspaceID, taskID, p)
	}
	q := taskQuery(workspaceID, taskID)
	q.Set("path", p)
	q.Set("ensure", "false")
	return t.download(ctx, "/sandbox/file-content", q, "Sandbox file", path.Base(p), domain.ContentTypeOf(p))
}

// open sends a GET to the manager with the file secret; redirects are not
// followed, as httpx does not. The body cancels the exchange once it has
// been idle for idle.
func (t taskFiles) open(ctx context.Context, p string, q url.Values, idle time.Duration) (*http.Response, error) {
	secret := t.s.d.Manager.FileSecret
	if secret == "" {
		return nil, api.ErrTaskFilesNotConfigured
	}
	reqCtx, cancel := context.WithCancel(ctx)
	timer := time.AfterFunc(idle, cancel)
	stop := func() {
		timer.Stop()
		cancel()
	}
	req, err := http.NewRequestWithContext(reqCtx, http.MethodGet, t.s.managerURL(p, q), nil)
	if err == nil {
		req.Header.Set("Authorization", "Bearer "+secret)
		client := *t.s.d.HTTP
		client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
		var resp *http.Response
		if resp, err = client.Do(req); err == nil {
			timer.Reset(idle)
			resp.Body = &idleBody{rc: resp.Body, timer: timer, idle: idle, stop: stop}
			return resp, nil
		}
	}
	stop()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	t.s.d.Log.WarnContext(ctx, "Sandbox manager request failed", "error", err)
	return nil, api.ErrTaskFilesUnavailable
}

type idleBody struct {
	rc    io.ReadCloser
	timer *time.Timer
	idle  time.Duration
	stop  func()
}

func (b *idleBody) Read(p []byte) (int, error) {
	n, err := b.rc.Read(p)
	b.timer.Reset(b.idle)
	return n, err
}

func (b *idleBody) Close() error {
	err := b.rc.Close()
	b.stop()
	return err
}

// readBody reads a whole answer; a failure mid-body is the manager being
// unavailable, as httpx raises it inside the request.
func (t taskFiles) readBody(ctx context.Context, resp *http.Response) ([]byte, error) {
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		t.s.d.Log.WarnContext(ctx, "Sandbox manager request failed", "error", err)
		return nil, api.ErrTaskFilesUnavailable
	}
	return raw, nil
}

func (t taskFiles) fetch(ctx context.Context, p string, q url.Values, resource string) ([]byte, error) {
	resp, err := t.open(ctx, p, q, taskFileRequestIdle)
	if err != nil {
		return nil, err
	}
	raw, err := t.readBody(ctx, resp)
	if err != nil {
		return nil, err
	}
	if err := t.statusError(ctx, resp.StatusCode, raw, resource); err != nil {
		return nil, err
	}
	return raw, nil
}

// statusError is _raise_sandbox_manager_error.
func (t taskFiles) statusError(ctx context.Context, status int, body []byte, resource string) error {
	switch {
	case status == http.StatusNotFound:
		return &api.TaskFileError{Status: http.StatusNotFound, Detail: resource + " not found"}
	case status == http.StatusGone:
		return api.ErrSandboxExpired
	case status >= 400:
		text := []rune(string(body))
		if len(text) > 300 {
			text = text[:300]
		}
		t.s.d.Log.WarnContext(ctx, "Sandbox manager request returned an error", "resource", resource, "status", status, "body", string(text))
		return api.ErrTaskFilesUnavailable
	}
	return nil
}

// download is _sandbox_manager_stream plus _stream_manager_download.
func (t taskFiles) download(ctx context.Context, p string, q url.Values, resource, filename, defaultType string) (api.Download, error) {
	resp, err := t.open(ctx, p, q, taskFileStreamIdle)
	if err != nil {
		return api.Download{}, err
	}
	if resp.StatusCode >= 400 {
		raw, err := t.readBody(ctx, resp)
		if err != nil {
			return api.Download{}, err
		}
		return api.Download{}, t.statusError(ctx, resp.StatusCode, raw, resource)
	}
	contentType := defaultType
	if v, ok := resp.Header["Content-Type"]; ok && len(v) > 0 {
		contentType = v[0]
	}
	h := downloadHeader(contentType, filename, resp.Header.Get("Content-Disposition"))
	if cl := resp.Header.Get("Content-Length"); cl != "" {
		h.Set("Content-Length", cl)
	}
	return api.Download{Body: resp.Body, Header: h}, nil
}

func downloadHeader(contentType, filename, disposition string) http.Header {
	h := SecureDownloadHeaders(contentType, filename, disposition, "artifact.bin")
	h.Set("Content-Type", starletteMediaType(contentType))
	return h
}

// starletteMediaType is the Content-Type Starlette sends for media_type.
func starletteMediaType(mt string) string {
	if strings.HasPrefix(mt, "text/") && !strings.Contains(strings.ToLower(mt), "charset=") {
		return mt + "; charset=utf-8"
	}
	return mt
}

func harnessPrefix(workspaceID, taskID string) string {
	return "harness-files/" + workspaceID + "/" + taskID + "/"
}

var errHarnessUnset = errors.New("the harness file bucket is not configured")

// harnessList is HarnessFiles.list.
func (t taskFiles) harnessList(ctx context.Context, workspaceID, taskID, prefix string) ([]string, error) {
	if t.s.d.Harness == nil {
		return nil, errHarnessUnset
	}
	root := harnessPrefix(workspaceID, taskID)
	paths := []string{}
	for info, err := range t.s.d.Harness.List(ctx, root+prefix) {
		if err != nil {
			return nil, err
		}
		paths = append(paths, strings.TrimPrefix(info.Key, root))
	}
	slices.Sort(paths)
	return paths, nil
}

// harnessGet is HarnessFiles.get answered as read_task_sandbox_file does.
func (t taskFiles) harnessGet(ctx context.Context, workspaceID, taskID, p string) (api.Download, error) {
	if t.s.d.Harness == nil {
		return api.Download{}, errHarnessUnset
	}
	body, info, err := t.s.d.Harness.Get(ctx, harnessPrefix(workspaceID, taskID)+p)
	if errors.Is(err, blob.ErrNotFound) {
		return api.Download{}, &api.TaskFileError{Status: http.StatusNotFound, Detail: "Sandbox file not found"}
	}
	if err != nil {
		return api.Download{}, err
	}
	contentType := info.ContentType
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	h := downloadHeader(contentType, path.Base(p), "")
	h.Set("Content-Length", strconv.FormatInt(info.Size, 10))
	return api.Download{Body: body, Header: h}, nil
}

// parseArtifactList is _ManagerArtifactList.model_validate.
func parseArtifactList(raw []byte) ([]api.TaskArtifact, error) {
	obj, err := decodeObject(raw)
	if err != nil {
		return nil, err
	}
	items, ok := obj["items"].([]any)
	if !ok {
		return nil, errors.New("items: input should be a valid list")
	}
	out := make([]api.TaskArtifact, 0, len(items))
	for i, rawItem := range items {
		item, ok := rawItem.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("items.%d: input should be an object", i)
		}
		a, err := parseArtifact(item)
		if err != nil {
			return nil, fmt.Errorf("items.%d.%w", i, err)
		}
		out = append(out, a)
	}
	return out, nil
}

func parseArtifact(item map[string]any) (api.TaskArtifact, error) {
	var a api.TaskArtifact
	for _, f := range []struct {
		name string
		dst  *string
	}{{"id", &a.ID}, {"path", &a.Path}, {"name", &a.Name}} {
		v, ok := item[f.name].(string)
		if !ok {
			return a, fmt.Errorf("%s: input should be a valid string", f.name)
		}
		*f.dst = v
	}
	for _, f := range []struct {
		name string
		dst  *string
	}{{"content_type", &a.ContentType}, {"sha256", &a.SHA256}} {
		raw, present := item[f.name]
		if !present {
			continue
		}
		v, ok := raw.(string)
		if !ok {
			return a, fmt.Errorf("%s: input should be a valid string", f.name)
		}
		*f.dst = v
	}
	size, ok := laxInt(item["size"])
	if !ok {
		return a, errors.New("size: input should be a valid integer")
	}
	a.Size = size
	if raw, present := item["created_at"]; present && raw != nil {
		s, ok := raw.(string)
		if !ok {
			return a, errors.New("created_at: input should be a valid datetime")
		}
		ts, err := parseDatetime(s)
		if err != nil {
			return a, fmt.Errorf("created_at: %w", err)
		}
		a.CreatedAt = &ts
	}
	return a, nil
}

// laxInt is pydantic's lax int: an integer, an integral float, a bool or a
// string holding an integer.
func laxInt(v any) (int64, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	case json.Number:
		if n, err := x.Int64(); err == nil {
			return n, true
		}
		f, err := x.Float64()
		if err != nil || f != float64(int64(f)) {
			return 0, false
		}
		return int64(f), true
	case string:
		n, err := strconv.ParseInt(strings.TrimSpace(x), 10, 64)
		return n, err == nil
	}
	return 0, false
}

// parseDatetime takes RFC 3339 with any of pydantic's date-time separators;
// a value without an offset is UTC, as UtcDatetime serializes it.
func parseDatetime(s string) (time.Time, error) {
	if len(s) > 10 && strings.ContainsRune(" t_", rune(s[10])) {
		s = s[:10] + "T" + s[11:]
	}
	if ts, err := time.Parse(time.RFC3339Nano, s); err == nil {
		return ts, nil
	}
	ts, err := time.ParseInLocation("2006-01-02T15:04:05.999999999", s, time.UTC)
	if err != nil {
		return time.Time{}, errors.New("input should be a valid datetime")
	}
	return ts, nil
}

// parsePathList is _ManagerSandboxFileList.model_validate.
func parsePathList(raw []byte) ([]string, error) {
	obj, err := decodeObject(raw)
	if err != nil {
		return nil, err
	}
	items, ok := obj["paths"].([]any)
	if !ok {
		return nil, errors.New("paths: input should be a valid list")
	}
	out := make([]string, 0, len(items))
	for i, v := range items {
		s, ok := v.(string)
		if !ok {
			return nil, fmt.Errorf("paths.%d: input should be a valid string", i)
		}
		out = append(out, s)
	}
	return out, nil
}
