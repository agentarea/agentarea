package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/projects"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// Mount registers the project routes on r behind workspace, the edge's
// middleware that admits the caller into /v1/workspaces/{workspace}. The
// file routes are registered only with files: they need the sandbox's store.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, s *Server, files bool) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	p := httpx.WorkspacePrefix + "/projects"
	id := []string{"project_id"}

	on(request{query: listQuery}).Get(p+"/", w.ListProjectsV1ProjectsGet)
	on(request{body: createBody}).Post(p+"/", w.CreateProjectV1ProjectsPost)
	on(request{pathUUIDs: id}).Get(p+"/{project_id}", w.GetProjectV1ProjectsProjectIdGet)
	on(request{pathUUIDs: id, body: updateBody}).Patch(p+"/{project_id}", w.UpdateProjectV1ProjectsProjectIdPatch)
	on(request{pathUUIDs: id}).Delete(p+"/{project_id}", w.DeleteProjectV1ProjectsProjectIdDelete)

	on(request{pathUUIDs: id, body: associationBody}).Post(p+"/{project_id}/skills", w.AddSkillToProjectV1ProjectsProjectIdSkillsPost)
	on(request{pathUUIDs: []string{"project_id", "skill_id"}}).Delete(p+"/{project_id}/skills/{skill_id}", w.RemoveSkillFromProjectV1ProjectsProjectIdSkillsSkillIdDelete)
	on(request{pathUUIDs: id, body: associationBody}).Post(p+"/{project_id}/mcp-instances", w.AddMcpInstanceToProjectV1ProjectsProjectIdMcpInstancesPost)
	on(request{pathUUIDs: []string{"project_id", "mcp_instance_id"}}).Delete(p+"/{project_id}/mcp-instances/{mcp_instance_id}", w.RemoveMcpInstanceFromProjectV1ProjectsProjectIdMcpInstancesMcpInstanceIdDelete)
	on(request{pathUUIDs: id, body: associationBody}).Post(p+"/{project_id}/agents", w.AddAgentToProjectV1ProjectsProjectIdAgentsPost)
	on(request{pathUUIDs: []string{"project_id", "agent_id"}}).Delete(p+"/{project_id}/agents/{agent_id}", w.RemoveAgentFromProjectV1ProjectsProjectIdAgentsAgentIdDelete)

	if !files {
		return
	}
	on(request{pathUUIDs: id, body: uploadPlanBody}).Post(p+"/{project_id}/files/upload-urls", w.PlanProjectUploadsV1ProjectsProjectIdFilesUploadUrlsPost)
	on(request{pathUUIDs: id}).Get(p+"/{project_id}/files", w.ListProjectFilesV1ProjectsProjectIdFilesGet)
	// {file_path:path} spans segments: chi's wildcard, read back as file_path.
	on(request{pathUUIDs: id}).With(filePath).Get(p+"/{project_id}/files/download/*", w.StreamProjectFileV1ProjectsProjectIdFilesDownloadFilePathGet)
	on(request{pathUUIDs: id}).With(filePath).Get(p+"/{project_id}/files/*", w.DownloadProjectFileV1ProjectsProjectIdFilesFilePathGet)
	on(request{pathUUIDs: id}).With(filePath).Delete(p+"/{project_id}/files/*", w.DeleteProjectFileV1ProjectsProjectIdFilesFilePathDelete)
}

func filePath(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rctx := chi.RouteContext(r.Context())
		rctx.URLParams.Add("file_path", rctx.URLParam("*"))
		next.ServeHTTP(w, r)
	})
}
