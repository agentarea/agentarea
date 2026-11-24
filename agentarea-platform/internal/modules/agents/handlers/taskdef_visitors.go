package handlers

import "net/http"

func (x response) VisitListTaskDefinitionsV1TaskDefinitionsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateTaskDefinitionV1TaskDefinitionsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteTaskDefinitionV1TaskDefinitionsDefinitionIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetTaskDefinitionV1TaskDefinitionsDefinitionIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateTaskDefinitionV1TaskDefinitionsDefinitionIdPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRunTaskDefinitionV1TaskDefinitionsDefinitionIdRunPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
