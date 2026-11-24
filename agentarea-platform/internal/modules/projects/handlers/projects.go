package handlers

import (
	"context"
	"errors"
	"net/http"
	"strconv"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/projects"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/service"
)

// Server implements the projects routes (api/v1/projects.py).
type Server struct {
	svc *service.Service
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service) *Server { return &Server{svc: svc} }

// caller is the workspace caller the edge resolved; a route mounted without
// the workspace middleware is a wiring bug.
func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

func workspace(ctx context.Context) (scope.Workspace, error) {
	c, err := caller(ctx)
	return c.Workspace, err
}

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var nf *domain.NotFoundError
	switch {
	case errors.Is(err, domain.ErrProjectNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Project not found"), true
	case errors.Is(err, service.ErrFileNotFound):
		return httpx.HTTPError(http.StatusNotFound, "File not found"), true
	case errors.As(err, &nf):
		return httpx.NotFound(nf.Error()), true
	case errors.Is(err, domain.ErrCycle):
		return httpx.BadRequest(domain.CycleDetail), true
	}
	return nil, false
}

func refs(rs []domain.Ref) []any {
	out := make([]any, len(rs))
	for i, r := range rs {
		out[i] = wirejson.Object{{Key: "id", Value: r.ID}, {Key: "name", Value: r.Name}}
	}
	return out
}

// projectJSON is ProjectResponse in its field order.
func projectJSON(p domain.Project) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: p.ID},
		{Key: "workspace_id", Value: p.WorkspaceID},
		{Key: "created_by", Value: p.CreatedBy},
		{Key: "name", Value: p.Name},
		{Key: "description", Value: p.Description},
		{Key: "instructions", Value: p.Instructions},
		{Key: "parent_project_id", Value: p.ParentProjectID},
		{Key: "skills", Value: refs(p.Skills)},
		{Key: "mcp_instances", Value: refs(p.MCPInstances)},
		{Key: "agents", Value: refs(p.Agents)},
	}
}

// response is a JSONResponse body as Starlette writes it, or an empty 204.
type response struct {
	status int
	body   any
}

func (x response) visit(w http.ResponseWriter) error {
	if x.status == http.StatusNoContent {
		w.WriteHeader(x.status)
		return nil
	}
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func (x response) VisitListProjectsV1ProjectsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateProjectV1ProjectsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetProjectV1ProjectsProjectIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateProjectV1ProjectsProjectIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteProjectV1ProjectsProjectIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddSkillToProjectV1ProjectsProjectIdSkillsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddAgentToProjectV1ProjectsProjectIdAgentsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitPlanProjectUploadsV1ProjectsProjectIdFilesUploadUrlsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListProjectFilesV1ProjectsProjectIdFilesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDownloadProjectFileV1ProjectsProjectIdFilesFilePathGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteProjectFileV1ProjectsProjectIdFilesFilePathDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func noContent() response { return response{status: http.StatusNoContent} }

func (s *Server) ListProjectsV1ProjectsGet(ctx context.Context, _ gen.ListProjectsV1ProjectsGetRequestObject) (gen.ListProjectsV1ProjectsGetResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	ps, err := s.svc.List(ctx, ws, in.limit, in.offset)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(ps))
	for i, p := range ps {
		out[i] = projectJSON(p)
	}
	return response{status: http.StatusOK, body: out}, nil
}

func (s *Server) CreateProjectV1ProjectsPost(ctx context.Context, _ gen.CreateProjectV1ProjectsPostRequestObject) (gen.CreateProjectV1ProjectsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	p, err := s.svc.Create(ctx, c.Workspace, c.UserID, inputFrom(ctx).create)
	if err != nil {
		return nil, err
	}
	p.Skills, p.MCPInstances, p.Agents = []domain.Ref{}, []domain.Ref{}, []domain.Ref{}
	return response{status: http.StatusCreated, body: projectJSON(p)}, nil
}

func (s *Server) GetProjectV1ProjectsProjectIdGet(ctx context.Context, rq gen.GetProjectV1ProjectsProjectIdGetRequestObject) (gen.GetProjectV1ProjectsProjectIdGetResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	p, err := s.svc.Get(ctx, ws, rq.ProjectId)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: projectJSON(p)}, nil
}

func (s *Server) UpdateProjectV1ProjectsProjectIdPatch(ctx context.Context, rq gen.UpdateProjectV1ProjectsProjectIdPatchRequestObject) (gen.UpdateProjectV1ProjectsProjectIdPatchResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	p, err := s.svc.Update(ctx, ws, rq.ProjectId, inputFrom(ctx).patch)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusOK, body: projectJSON(p)}, nil
}

func (s *Server) DeleteProjectV1ProjectsProjectIdDelete(ctx context.Context, rq gen.DeleteProjectV1ProjectsProjectIdDeleteRequestObject) (gen.DeleteProjectV1ProjectsProjectIdDeleteResponseObject, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.Delete(ctx, ws, rq.ProjectId); err != nil {
		return nil, err
	}
	return noContent(), nil
}

func (s *Server) link(ctx context.Context, k domain.LinkKind, project uuid.UUID) (response, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return response{}, err
	}
	if err := s.svc.Link(ctx, ws, k, project, inputFrom(ctx).association); err != nil {
		return response{}, err
	}
	return noContent(), nil
}

func (s *Server) unlink(ctx context.Context, k domain.LinkKind, project, child uuid.UUID) (response, error) {
	ws, err := workspace(ctx)
	if err != nil {
		return response{}, err
	}
	if err := s.svc.Unlink(ctx, ws, k, project, child); err != nil {
		return response{}, err
	}
	return noContent(), nil
}

func (s *Server) AddSkillToProjectV1ProjectsProjectIdSkillsPost(ctx context.Context, rq gen.AddSkillToProjectV1ProjectsProjectIdSkillsPostRequestObject) (gen.AddSkillToProjectV1ProjectsProjectIdSkillsPostResponseObject, error) {
	return s.link(ctx, domain.LinkSkill, rq.ProjectId)
}

func (s *Server) RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDelete(ctx context.Context, rq gen.RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteRequestObject) (gen.RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDeleteResponseObject, error) {
	return s.unlink(ctx, domain.LinkSkill, rq.ProjectId, rq.SkillId)
}

func (s *Server) AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPost(ctx context.Context, rq gen.AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostRequestObject) (gen.AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPostResponseObject, error) {
	return s.link(ctx, domain.LinkMCPInstance, rq.ProjectId)
}

func (s *Server) RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDelete(ctx context.Context, rq gen.RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteRequestObject) (gen.RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDeleteResponseObject, error) {
	return s.unlink(ctx, domain.LinkMCPInstance, rq.ProjectId, rq.McpInstanceId)
}

func (s *Server) AddAgentToProjectV1ProjectsProjectIdAgentsPost(ctx context.Context, rq gen.AddAgentToProjectV1ProjectsProjectIdAgentsPostRequestObject) (gen.AddAgentToProjectV1ProjectsProjectIdAgentsPostResponseObject, error) {
	return s.link(ctx, domain.LinkAgent, rq.ProjectId)
}

func (s *Server) RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDelete(ctx context.Context, rq gen.RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteRequestObject) (gen.RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDeleteResponseObject, error) {
	return s.unlink(ctx, domain.LinkAgent, rq.ProjectId, rq.AgentId)
}
