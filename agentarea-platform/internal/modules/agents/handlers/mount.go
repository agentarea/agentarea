package handlers

import (
	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// Mount registers the routes on r; workspace routes behind e.Workspace, the
// edge's middleware that admits the caller into /v1/workspaces/{workspace}.
func Mount(r chi.Router, errs *httpx.Errors, e Edge, s *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(e.Workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	p := httpx.WorkspacePrefix + "/agents"

	on(request{}).Get(p, w.ListAgentsV1AgentsGet)
	on(request{}).Get(p+"/", w.ListAgentsV1AgentsGetDup2)
	on(request{body: createBody}).Post(p+"/", w.CreateAgentV1AgentsPost)
	mountMisc(r, on, w, e, s, errs)
	on(request{}).Get(p+"/{agent_id}", w.GetAgentV1AgentsAgentIdGet)
	on(request{body: updateBody}).Patch(p+"/{agent_id}", w.UpdateAgentV1AgentsAgentIdPatch)
	on(request{}).Delete(p+"/{agent_id}", w.DeleteAgentV1AgentsAgentIdDelete)
	on(request{}).Post(p+"/{agent_id}/restore", w.RestoreAgentV1AgentsAgentIdRestorePost)

	c := httpx.WorkspacePrefix + "/skill-collections"
	cid := []string{"collection_id"}
	on(request{}).Get(c+"/", w.ListCollectionsV1SkillCollectionsGet)
	on(request{body: collectionBody(true)}).Post(c+"/", w.CreateCollectionV1SkillCollectionsPost)
	on(request{pathUUIDs: cid}).Get(c+"/{collection_id}", w.GetCollectionV1SkillCollectionsCollectionIdGet)
	on(request{pathUUIDs: cid, body: collectionBody(false)}).Put(c+"/{collection_id}", w.UpdateCollectionV1SkillCollectionsCollectionIdPut)
	on(request{pathUUIDs: cid}).Delete(c+"/{collection_id}", w.DeleteCollectionV1SkillCollectionsCollectionIdDelete)
	on(request{pathUUIDs: cid, body: addSkillBody}).Post(c+"/{collection_id}/skills", w.AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPost)
	on(request{pathUUIDs: []string{"collection_id", "skill_id"}}).Delete(c+"/{collection_id}/skills/{skill_id}", w.RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDelete)

	mountSkills(r, on, w, e, s, errs)
	mountClients(r, on, w, e, s, errs)
	mountTaskDefs(r, on, w, e, s, errs)
	mountA2A(r, on, w, e, s, errs)
}
