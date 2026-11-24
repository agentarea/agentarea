package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"path"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

const maxNameTries = 100

// attachFiles copies workspace files into a task under inputs/attachments/ and answers their
// descriptors. Into a live task a name another file already holds gets a numbered one, so the
// change stays the pure addition its running sandbox takes in.
func (s *Surface) attachFiles(ctx context.Context, ws scope.Workspace, taskID string, files []api.TaskAttachment, live bool) ([]any, error) {
	if s.d.Workspaces == nil {
		return nil, errors.New("task attachments need the sandbox workspace port")
	}
	used := map[string]bool{}
	out := make([]any, 0, len(files))
	for _, f := range files {
		name, err := s.freeName(ctx, ws, taskID, f, used, live)
		if err != nil {
			return nil, err
		}
		used[name] = true
		ct := f.ContentType
		if ct == "" {
			ct = "application/octet-stream"
		}
		rel := "inputs/attachments/" + name
		if _, err := s.d.Workspaces.AttachObject(ctx, ws.ID(), taskID, rel,
			sandboxapi.AttachSource{Key: f.Key, SHA256: f.SHA256, Size: f.Size, ContentType: ct},
			sandboxapi.WriteOptions{Owner: "task-attachment-event-" + taskID}); err != nil {
			return nil, fmt.Errorf("attaching %s to task %s: %w", f.Key, taskID, err)
		}
		out = append(out, map[string]any{"relative_path": rel, "filename": name, "size": f.Size, "content_type": ct, "sha256": f.SHA256})
	}
	return out, nil
}

// freeName is f's name, or name-1.ext, name-2.ext, ...: the first not taken in this call and, in
// a live task, not holding other content.
func (s *Surface) freeName(ctx context.Context, ws scope.Workspace, taskID string, f api.TaskAttachment, used map[string]bool, live bool) (string, error) {
	base := f.Name
	if base == "" {
		base = "attachment"
	}
	ext := path.Ext(base)
	stem := strings.TrimSuffix(base, ext)
	for i := 0; i < maxNameTries; i++ {
		name := base
		if i > 0 {
			name = stem + "-" + strconv.Itoa(i) + ext
		}
		if used[name] {
			continue
		}
		if !live {
			return name, nil
		}
		data, _, err := s.d.Workspaces.Get(ctx, ws.ID(), taskID, "inputs/attachments/"+name)
		if errors.Is(err, sandboxapi.ErrFileNotFound) {
			return name, nil
		}
		if err != nil {
			return "", err
		}
		sum := sha256.Sum256(data)
		if hex.EncodeToString(sum[:]) == f.SHA256 {
			return name, nil
		}
	}
	return "", fmt.Errorf("task %s holds too many files named %s", taskID, base)
}

// attachedLines tell a running task where the files a follow-up brought are.
func attachedLines(descriptors []any) string {
	lines := make([]string, 0, len(descriptors))
	for _, d := range descriptors {
		m, _ := d.(map[string]any)
		size, _ := m["size"].(int64)
		lines = append(lines, fmt.Sprintf("Attached file: %s (%s, %.1f MB)", m["relative_path"], m["content_type"], float64(size)/(1<<20)))
	}
	return strings.Join(lines, "\n")
}
