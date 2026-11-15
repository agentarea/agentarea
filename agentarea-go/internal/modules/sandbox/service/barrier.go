package service

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

const outputsDir = "outputs"

func normalizeDeclared(raw string) (string, error) {
	candidate := strings.TrimSpace(raw)
	for _, prefix := range []string{"/workspace/", "./"} {
		if strings.HasPrefix(candidate, prefix) {
			candidate = candidate[len(prefix):]
			break
		}
	}
	return domain.NormalizeWorkspacePath(candidate)
}

func storeUnavailable(msg string) api.ArtifactValidation {
	return api.ArtifactValidation{
		State: "unavailable", Capability: "published_artifact_store",
		Issues: []api.ArtifactIssue{{Validator: "published_artifact", Code: "capability_unavailable", Message: msg}},
	}
}

// ValidateArtifacts is validate_published_artifacts: every declared path and
// every file under outputs/ is published before the task completes.
func (r runtime) ValidateArtifacts(ctx context.Context, workspaceID, taskID string, declaredPaths []string) (api.ArtifactValidation, error) {
	var declared []string
	for _, raw := range declaredPaths {
		p, err := normalizeDeclared(raw)
		if err != nil {
			return api.ArtifactValidation{State: "failed", Issues: []api.ArtifactIssue{{
				Path: raw, Validator: "published_artifact", Code: "invalid_artifact_path", Message: err.Error(),
			}}}, nil
		}
		if !containsString(declared, p) {
			declared = append(declared, p)
		}
	}
	m := r.s.d.Manager
	if m.URL == "" || m.FileSecret == "" {
		if len(declared) == 0 {
			return api.ArtifactValidation{State: "passed"}, nil
		}
		return storeUnavailable("artifact store authentication is not configured"), nil
	}
	outputs, fail := r.outputsInSandbox(ctx, workspaceID, taskID)
	if fail != nil {
		return *fail, ctx.Err()
	}
	for _, p := range outputs {
		if !containsString(declared, p) {
			declared = append(declared, p)
		}
	}
	var out api.ArtifactValidation
	for _, p := range declared {
		body, err := json.Marshal(map[string]string{"workspace_id": workspaceID, "task_id": taskID, "path": p})
		if err != nil {
			return api.ArtifactValidation{}, err
		}
		h := bearer(m.FileSecret)
		h.Set("Content-Type", "application/json")
		resp, err := r.s.call(ctx, http.MethodPost, r.s.managerURL("/sandbox/artifacts", nil), h, body, 60*time.Second)
		if err != nil {
			if ctx.Err() != nil {
				return api.ArtifactValidation{}, ctx.Err()
			}
			r.s.d.Log.WarnContext(ctx, "artifact store could not be reached", "error", err)
			return storeUnavailable("artifact store could not be reached"), nil
		}
		ev, issue, blocked := publicationOutcome(p, resp)
		switch {
		case blocked != nil:
			return *blocked, nil
		case issue != nil:
			out.Issues = append(out.Issues, *issue)
		default:
			out.Evidence = append(out.Evidence, *ev)
		}
	}
	out.State = "passed"
	if len(out.Issues) > 0 {
		out.State = "failed"
	}
	return out, nil
}

func (r runtime) outputsInSandbox(ctx context.Context, workspaceID, taskID string) ([]string, *api.ArtifactValidation) {
	q := url.Values{"workspace_id": {workspaceID}, "task_id": {taskID}, "list": {outputsDir}, "ensure": {"false"}}
	resp, err := r.s.call(ctx, http.MethodGet, r.s.managerURL("/sandbox/files", q), bearer(r.s.d.Manager.FileSecret), nil, 60*time.Second)
	if err != nil {
		r.s.d.Log.WarnContext(ctx, "sandbox outputs could not be listed", "error", err)
		v := storeUnavailable("sandbox outputs could not be listed")
		return nil, &v
	}
	if resp.Status == http.StatusGone {
		return nil, nil
	}
	if resp.Status != http.StatusOK {
		v := storeUnavailable(fmt.Sprintf("sandbox outputs listing returned HTTP %d", resp.Status))
		return nil, &v
	}
	invalid := func() ([]string, *api.ArtifactValidation) {
		v := storeUnavailable("sandbox outputs listing returned an invalid response")
		return nil, &v
	}
	body, err := decodeObject(resp.Body)
	if err != nil {
		return invalid()
	}
	raw, ok := body["paths"].([]any)
	if !ok {
		return invalid()
	}
	var out []string
	for _, item := range raw {
		p, err := normalizeDeclared(strOf(item))
		if err != nil {
			return invalid()
		}
		if strings.HasPrefix(p, outputsDir+"/") {
			out = append(out, p)
		}
	}
	return out, nil
}

func publicationOutcome(p string, resp managerResponse) (*api.ArtifactEvidence, *api.ArtifactIssue, *api.ArtifactValidation) {
	blocked := func(msg string) (*api.ArtifactEvidence, *api.ArtifactIssue, *api.ArtifactValidation) {
		v := storeUnavailable(msg)
		return nil, nil, &v
	}
	switch resp.Status {
	case http.StatusNotFound:
		return nil, &api.ArtifactIssue{Path: p, Validator: "published_artifact", Code: "artifact_missing",
			Message: "the response declares this file but it is not in the workspace; write it before completing, or drop it from artifacts"}, nil
	case http.StatusRequestEntityTooLarge:
		return nil, &api.ArtifactIssue{Path: p, Validator: "published_artifact", Code: "artifact_quota_exceeded",
			Message: "declared file exceeds the task artifact quota"}, nil
	case http.StatusCreated:
	default:
		return blocked(fmt.Sprintf("artifact store returned HTTP %d for %s", resp.Status, p))
	}
	item, err := decodeObject(resp.Body)
	if err != nil {
		return blocked("artifact store returned an invalid response")
	}
	rawSHA, hasSHA := item["sha256"]
	rawSize, hasSize := item["size"]
	if !hasSHA || !hasSize {
		return blocked("artifact store returned an invalid response")
	}
	sha := strOf(rawSHA)
	size, isInt := pyInt(rawSize)
	if !isSHA256(sha) || !isInt || size < 0 {
		return blocked(fmt.Sprintf("published artifact %s has no valid identity", p))
	}
	return &api.ArtifactEvidence{Path: p, Validator: "published_artifact", SHA256: sha, Size: size}, nil, nil
}

// pyInt is isinstance(v, int) over a decoded JSON value; a bool counts.
func pyInt(v any) (int64, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	case json.Number:
		n, err := x.Int64()
		return n, err == nil && !strings.ContainsAny(x.String(), ".eE")
	}
	return 0, false
}
