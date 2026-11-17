package handlers

import "net/http"

func (x response) VisitListClientsV1ClientsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateClientV1ClientsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListPlatformToolsetsV1ClientsPlatformToolsetsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteClientV1ClientsClientIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetClientV1ClientsClientIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateClientV1ClientsClientIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitHarnessAgentV1ClientsClientIdAgentPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddMcpInstanceToClientV1ClientsClientIdMcpInstancesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddOpenapiConnectionToClientV1ClientsClientIdOpenapiConnectionsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveOpenapiConnectionFromClientV1ClientsClientIdOpenapiConnectionsConnectionIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddPlatformToolsetToClientV1ClientsClientIdPlatformToolsetsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListRunnerKeysV1ClientsClientIdRunnerKeysGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitIssueRunnerKeyV1ClientsClientIdRunnerKeysPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRevokeRunnerKeyV1ClientsClientIdRunnerKeysKeyIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddSkillToClientV1ClientsClientIdSkillsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
