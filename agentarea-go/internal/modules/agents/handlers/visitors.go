package handlers

import "net/http"

func (x response) VisitListAgentsV1AgentsGetResponse(w http.ResponseWriter) error { return x.visit(w) }
func (x response) VisitListAgentsV1AgentsGetDup2Response(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateAgentV1AgentsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetAgentV1AgentsAgentIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateAgentV1AgentsAgentIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteAgentV1AgentsAgentIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRestoreAgentV1AgentsAgentIdRestorePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListCollectionsV1SkillCollectionsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateCollectionV1SkillCollectionsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetCollectionV1SkillCollectionsCollectionIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateCollectionV1SkillCollectionsCollectionIdPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteCollectionV1SkillCollectionsCollectionIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
