package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// Workspace file bounds (files_toolset.py).
const (
	fileReadMaxBytes    = 512 * 1024
	maxUploadsPerPlan   = 100
	defaultFileMaxItems = 200
	defaultURLExpiresIn = 3600
)

var errFileNotFound = &toolError{"File not found"}

// slugged is ws named by its slug too: a run enters its workspace by id alone.
func slugged(ctx context.Context, ws scope.Workspace, slugs identityapi.WorkspaceSlugs) (scope.Workspace, error) {
	if ws.Slug() != "" {
		return ws, nil
	}
	if slugs == nil {
		return scope.Workspace{}, errors.New("the workspace's slug is unknown and no slug reader is wired")
	}
	slug, err := slugs.Slug(ctx, ws.ID())
	if err != nil {
		return scope.Workspace{}, err
	}
	return scope.NewWorkspace(ws.ID(), slug)
}

type filePathArgs struct {
	Path string `json:"path"`
}

// workspaceFileTools is tools/files_toolset.py.
func workspaceFileTools(f sandboxapi.PlatformFiles, slugs identityapi.WorkspaceSlugs) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List workspace files", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Prefix   string `json:"prefix"`
				MaxItems *int   `json:"max_items"`
			}](args)
			if err != nil {
				return nil, err
			}
			maxItems := defaultFileMaxItems
			if in.MaxItems != nil {
				maxItems = *in.MaxItems
			}
			maxItems = max(1, min(maxItems, maxListedFiles))
			files, err := f.ListFiles(ctx, c.Workspace, in.Prefix, maxItems)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(files))
			for i, o := range files {
				var ct any
				if o.ContentType != "" {
					ct = o.ContentType
				}
				out[i] = map[string]any{"path": o.Path, "size": o.Size, "content_type": ct, "last_modified": o.LastModified}
			}
			return out, nil
		}},
		"get_url": {title: "Get workspace file URL", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Path      string `json:"path"`
				ExpiresIn *int   `json:"expires_in"`
			}](args)
			if err != nil {
				return nil, err
			}
			expires := defaultURLExpiresIn
			if in.ExpiresIn != nil {
				expires = *in.ExpiresIn
			}
			ok, err := f.FileExists(ctx, c.Workspace, in.Path)
			if err != nil {
				return nil, err
			}
			if !ok {
				return nil, errFileNotFound
			}
			ws, err := slugged(ctx, c.Workspace, slugs)
			if err != nil {
				return nil, err
			}
			return map[string]any{"url": f.DownloadURL(ws, in.Path), "path": in.Path, "expires_in": expires}, nil
		}},
		"read": {title: "Read workspace file", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[filePathArgs](args)
			if err != nil {
				return nil, err
			}
			body, err := f.ReadFile(ctx, c.Workspace, in.Path)
			if errors.Is(err, sandboxapi.ErrFileNotFound) || errors.Is(err, sandboxapi.ErrInvalidPath) {
				return nil, errFileNotFound
			}
			if err != nil {
				return nil, err
			}
			if len(body) > fileReadMaxBytes {
				return nil, &toolError{fmt.Sprintf("File is larger than %d bytes; use get_url", fileReadMaxBytes)}
			}
			if !utf8.Valid(body) {
				return nil, &toolError{"File is not UTF-8 text; use get_url"}
			}
			return map[string]any{"path": in.Path, "content": string(body)}, nil
		}},
		"upload_urls": {title: "Get workspace file upload URLs", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Files []map[string]string `json:"files"`
			}](args)
			if err != nil {
				return nil, err
			}
			if len(in.Files) == 0 {
				return nil, &toolError{"files must not be empty"}
			}
			if len(in.Files) > maxUploadsPerPlan {
				return nil, &toolError{fmt.Sprintf("at most %d files per call", maxUploadsPerPlan)}
			}
			entries := make([]sandboxapi.UploadEntry, len(in.Files))
			for i, e := range in.Files {
				entries[i] = sandboxapi.UploadEntry{Path: e["path"], SHA256: e["sha256"]}
				if ct, ok := e["content_type"]; ok {
					entries[i].ContentType = &ct
				}
			}
			planned, err := f.PlanUploads(ctx, c.Workspace, c.UserID, entries)
			if err != nil {
				return nil, err
			}
			uploads := make([]map[string]any, len(planned))
			for i, p := range planned {
				var headers any
				if p.Headers != nil {
					headers = p.Headers
				}
				uploads[i] = map[string]any{"path": p.Path, "status": p.Status, "upload_url": p.UploadURL, "method": p.Method,
					"headers": headers, "expires_in": p.ExpiresIn, "error": p.Error}
			}
			return map[string]any{"uploads": uploads}, nil
		}},
		"delete": {title: "Delete workspace file", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[filePathArgs](args)
			if err != nil {
				return nil, err
			}
			err = f.DeleteFile(ctx, c.Workspace, in.Path)
			var ro *sandboxapi.ReadOnlyError
			switch {
			case errors.As(err, &ro):
				return nil, &toolError{ro.Msg}
			case errors.Is(err, sandboxapi.ErrFileNotFound):
				return nil, errFileNotFound
			case err != nil:
				return nil, err
			}
			return map[string]any{"deleted": true, "path": in.Path}, nil
		}},
	}
}
