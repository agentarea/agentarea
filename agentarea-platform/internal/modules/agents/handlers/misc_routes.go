package handlers

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"strconv"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

type miscInput struct {
	tools service.ToolsQuery
}

// miscLast is the value FastAPI binds for a scalar query parameter: the last one sent.
func miscLast(q map[string][]string, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

func toolsQuery(q map[string][]string, in *input, errs *[]httpx.FieldError) {
	tq := service.ToolsQuery{Include: "code,mcp"}
	if v, ok := miscLast(q, "include"); ok {
		tq.Include = v
	}
	if v, ok := miscLast(q, "mcp_instance_id"); ok {
		id, fe := httpx.ValidateUUID(v, "query", "mcp_instance_id")
		if fe != nil {
			*errs = append(*errs, *fe)
		}
		tq.MCPInstanceID = id
	}
	in.area = miscInput{tools: tq}
}

// toolsCanonicalQuery leaves the generated binder one value per parameter.
func toolsCanonicalQuery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tq := areaInput[miscInput](r.Context()).tools
		q := url.Values{"include": {tq.Include}}
		if tq.MCPInstanceID != "" {
			q.Set("mcp_instance_id", tq.MCPInstanceID)
		}
		r.URL.RawQuery = q.Encode()
		next.ServeHTTP(w, r)
	})
}

// mountMisc registers GET /agents/tools, /agents/presets, POST /agents/{agent_id}/install and GET /export.
func mountMisc(_ chi.Router, on func(rq request) chi.Router, w *gen.ServerInterfaceWrapper, _ Edge, _ *Server, _ *httpx.Errors) {
	p := httpx.WorkspacePrefix + "/agents"
	on(request{query: toolsQuery}).With(toolsCanonicalQuery).Get(p+"/tools", w.GetAllToolsV1AgentsToolsGet)
	on(request{}).Get(p+"/presets", w.ListAgentPresetsV1AgentsPresetsGet)
	on(request{}).Post(p+"/{agent_id}/install", w.InstallAgentV1AgentsAgentIdInstallPost)
	on(request{}).Get(httpx.WorkspacePrefix+"/export", w.ExportWorkspaceConfigV1ExportGet)
}

// exportFailed is the export route's catch-all: any other error is a 500.
type exportFailed struct{ cause error }

func (e *exportFailed) Error() string { return e.cause.Error() }
func (e *exportFailed) Unwrap() error { return e.cause }

func mapMiscError(err error) (*httpx.Error, bool) {
	var inv *api.ExportInvalidError
	var failed *exportFailed
	var preset *service.PresetMalformedError
	switch {
	case errors.As(err, &inv):
		return httpx.HTTPError(http.StatusUnprocessableEntity, inv.Msg), true
	case errors.As(err, &failed):
		return httpx.HTTPError(http.StatusInternalServerError, "Internal server error").Wrap(failed.cause), true
	case errors.As(err, &preset):
		return httpx.HTTPError(http.StatusInternalServerError, preset.Error()), true
	}
	return nil, false
}

func (s *Server) GetAllToolsV1AgentsToolsGet(ctx context.Context, _ gen.GetAllToolsV1AgentsToolsGetRequestObject) (gen.GetAllToolsV1AgentsToolsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	tools, err := s.ext.Misc.Tools(ctx, c, areaInput[miscInput](ctx).tools)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(tools))
	for i, t := range tools {
		out[i] = t
	}
	return ok(out), nil
}

func (s *Server) ListAgentPresetsV1AgentsPresetsGet(ctx context.Context, _ gen.ListAgentPresetsV1AgentsPresetsGetRequestObject) (gen.ListAgentPresetsV1AgentsPresetsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	body, err := s.ext.Misc.Presets(ctx, c)
	if err != nil {
		return nil, err
	}
	return ok(body), nil
}

func (s *Server) InstallAgentV1AgentsAgentIdInstallPost(ctx context.Context, rq gen.InstallAgentV1AgentsAgentIdInstallPostRequestObject) (gen.InstallAgentV1AgentsAgentIdInstallPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.ext.Misc.Install(ctx, c, rq.AgentId)
	if err != nil {
		return nil, err
	}
	return ok(agentJSON(v, true)), nil
}

func (s *Server) ExportWorkspaceConfigV1ExportGet(ctx context.Context, _ gen.ExportWorkspaceConfigV1ExportGetRequestObject) (gen.ExportWorkspaceConfigV1ExportGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.RequireAdmin(ctx); err != nil {
		return nil, err
	}
	yaml, err := s.ext.Misc.ExportYAML(ctx, c)
	if err != nil {
		var inv *api.ExportInvalidError
		var unwired *service.UnwiredError
		if errors.As(err, &inv) || errors.As(err, &unwired) {
			return nil, err
		}
		return nil, &exportFailed{cause: err}
	}
	return exportText(yaml), nil
}

// exportText is PlainTextResponse with the attachment disposition.
type exportText string

func (x exportText) VisitExportWorkspaceConfigV1ExportGetResponse(w http.ResponseWriter) error {
	w.Header().Set("Content-Disposition", "attachment; filename=workspace_config.yaml")
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Content-Length", strconv.Itoa(len(x)))
	w.WriteHeader(http.StatusOK)
	_, err := w.Write([]byte(x))
	return err
}

func (x response) VisitGetAllToolsV1AgentsToolsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListAgentPresetsV1AgentsPresetsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitInstallAgentV1AgentsAgentIdInstallPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
