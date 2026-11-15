package handlers

import (
	"mime"
	"net/http"
	"net/url"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
)

// mountSkills registers the Skills routes.
func mountSkills(_ chi.Router, on func(rq request) chi.Router, w *gen.ServerInterfaceWrapper, _ Edge, _ *Server, errs *httpx.Errors) {
	p := httpx.WorkspacePrefix + "/skills"
	sid := []string{"skill_id"}

	on(request{body: createSkillBody}).Post(p, w.CreateSkillV1SkillsPost)
	on(request{query: uploadQuery}).With(skillMultipart(errs)).Post(p+"/upload", w.UploadSkillV1SkillsUploadPost)
	on(request{query: listSkillsQuery}).Get(p, w.ListSkillsV1SkillsGet)
	on(request{}).Post(p+"/update-all", w.UpdateAllSkillsV1SkillsUpdateAllPost)
	on(request{pathUUIDs: sid}).Get(p+"/{skill_id}", w.GetSkillV1SkillsSkillIdGet)
	on(request{pathUUIDs: sid, query: boolQuery("discard_changes", false, func(s *skillInput, b bool) { s.discard = b })}).
		Post(p+"/{skill_id}/update", w.UpdateInstalledSkillV1SkillsSkillIdUpdatePost)
	on(request{pathUUIDs: sid}).Get(p+"/{skill_id}/versions", w.ListSkillVersionsV1SkillsSkillIdVersionsGet)
	on(request{pathUUIDs: []string{"skill_id", "version_id"}}).
		Post(p+"/{skill_id}/versions/{version_id}/rollback", w.RollbackSkillV1SkillsSkillIdVersionsVersionIdRollbackPost)
	on(request{pathUUIDs: sid}).Post(p+"/{skill_id}/install", w.InstallSkillV1SkillsSkillIdInstallPost)
	on(request{pathUUIDs: sid}).Get(p+"/{skill_id}/content", w.GetSkillContentV1SkillsSkillIdContentGet)
	on(request{pathUUIDs: sid, query: boolQuery("include_urls", false, func(s *skillInput, b bool) { s.includeURLs = b })}).
		Get(p+"/{skill_id}/files", w.ListSkillFilesV1SkillsSkillIdFilesGet)
	on(request{pathUUIDs: sid, query: boolQuery("redirect", true, func(s *skillInput, b bool) { s.redo = b })}).
		Get(p+"/{skill_id}/files/*", skillFileRoute(w))
	on(request{pathUUIDs: sid, body: updateSkillBody}).Put(p+"/{skill_id}", w.UpdateSkillV1SkillsSkillIdPut)
	on(request{pathUUIDs: sid}).Delete(p+"/{skill_id}", w.DeleteSkillV1SkillsSkillIdDelete)
	on(request{pathUUIDs: sid, body: memberBody}).Post(p+"/{skill_id}/members", w.AddSkillMemberV1SkillsSkillIdMembersPost)
	on(request{pathUUIDs: sid}).Get(p+"/{skill_id}/members", w.ListSkillMembersV1SkillsSkillIdMembersGet)
	on(request{pathUUIDs: []string{"skill_id", "child_skill_id"}}).
		Delete(p+"/{skill_id}/members/{child_skill_id}", w.RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDelete)
	on(request{pathUUIDs: sid}).Get(p+"/{skill_id}/flatten", w.FlattenSkillMembersV1SkillsSkillIdFlattenGet)
}

// skillFileRoute is /{skill_id}/files/{path:path}: the rest of the path,
// slashes included, is the file path.
func skillFileRoute(w *gen.ServerInterfaceWrapper) http.HandlerFunc {
	return func(rw http.ResponseWriter, r *http.Request) {
		path := chi.URLParam(r, "*")
		if r.URL.RawPath != "" {
			if p, err := url.PathUnescape(path); err == nil {
				path = p
			}
		}
		w.Handler.GetSkillFileV1SkillsSkillIdFilesPathGet(rw, r, chi.URLParam(r, httpx.WorkspaceParam),
			uuid.MustParse(chi.URLParam(r, "skill_id")), path, gen.GetSkillFileV1SkillsSkillIdFilesPathGetParams{})
	}
}

// skillMultipart answers a body that is not multipart as FastAPI does: the
// required file field is missing.
func skillMultipart(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			mt, params, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
			if err != nil || mt != "multipart/form-data" || params["boundary"] == "" {
				errs.Write(w, r, httpx.Validation(httpx.Missing("body", "file")))
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
