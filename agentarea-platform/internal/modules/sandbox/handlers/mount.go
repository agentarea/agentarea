package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/sandbox"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// Mount registers the files and sandboxes routes on r behind workspace, the
// edge's middleware that admits the caller into /v1/workspaces/{workspace}.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, s *Server) {
	strict := gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
		RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
	})
	w := &gen.ServerInterfaceWrapper{Handler: strict, ErrorHandlerFunc: errs.Write}
	base := r.With(workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	ws := func(r *http.Request) string { return chi.URLParam(r, httpx.WorkspaceParam) }
	tail := func(r *http.Request) string { return inputFrom(r.Context()).filePath }
	p := httpx.WorkspacePrefix + "/files"

	on(request{}).Get(p, w.ListWorkspaceFilesV1FilesGet)
	on(request{body: directoryBody}).Post(p+"/directories", w.CreateWorkspaceDirectoryV1FilesDirectoriesPost)
	on(request{body: presignBody}).Post(p+"/upload-url", w.CreateAttachmentUploadUrlV1FilesUploadUrlPost)
	on(request{body: uploadPlanBody}).Post(p+"/upload-urls", w.PlanWorkspaceUploadsV1FilesUploadUrlsPost)
	on(request{body: moveBody}).Post(p+"/move", w.MoveWorkspaceFileV1FilesMovePost)
	// {file_path:path} spans segments: chi's wildcard, decoded by the
	// request middleware and handed to the strict handler as is.
	on(request{filePath: true}).Delete(p+"/*", func(rw http.ResponseWriter, r *http.Request) {
		strict.DeleteWorkspaceFileV1FilesFilePathDelete(rw, r, ws(r), tail(r))
	})
	on(request{filePath: true}).Post(p+"/restore/*", func(rw http.ResponseWriter, r *http.Request) {
		strict.RestoreWorkspaceFileV1FilesRestoreFilePathPost(rw, r, ws(r), tail(r))
	})
	on(request{query: historyQuery}).Get(p+"/history", func(rw http.ResponseWriter, r *http.Request) {
		strict.WorkspaceFileHistoryV1FilesHistoryGet(rw, r, ws(r), gen.WorkspaceFileHistoryV1FilesHistoryGetParams{Path: inputFrom(r.Context()).historyPath})
	})
	on(request{filePath: true}).Get(p+"/download/*", func(rw http.ResponseWriter, r *http.Request) {
		strict.StreamWorkspaceFileV1FilesDownloadFilePathGet(rw, r, ws(r), tail(r))
	})
	on(request{filePath: true}).Get(p+"/*", func(rw http.ResponseWriter, r *http.Request) {
		strict.DownloadWorkspaceFileV1FilesFilePathGet(rw, r, ws(r), tail(r))
	})
	on(request{}).Get(httpx.WorkspacePrefix+"/sandboxes", w.ListSandboxesV1SandboxesGet)
}
