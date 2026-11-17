package handlers

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// mountTaskDefs registers the TaskDefs routes.
func mountTaskDefs(r chi.Router, _ func(rq request) chi.Router, w *gen.ServerInterfaceWrapper, e Edge, s *Server, errs *httpx.Errors) {
	p := httpx.WorkspacePrefix + "/task-definitions"
	id := []string{"definition_id"}
	clientChain(r, e, errs, request{query: taskDefListQuery}).Get(p+"/", w.ListTaskDefinitionsV1TaskDefinitionsGet)
	clientChain(r, e, errs, request{body: taskDefCreateBody}).Post(p+"/", w.CreateTaskDefinitionV1TaskDefinitionsPost)
	clientChain(r, e, errs, request{pathUUIDs: id}).Get(p+"/{definition_id}", w.GetTaskDefinitionV1TaskDefinitionsDefinitionIdGet)
	clientChain(r, e, errs, request{pathUUIDs: id, body: taskDefUpdateBody}, clientRequires(s, errs, "edit", "definition_id")).
		Put(p+"/{definition_id}", w.UpdateTaskDefinitionV1TaskDefinitionsDefinitionIdPut)
	clientChain(r, e, errs, request{pathUUIDs: id}, clientRequires(s, errs, "delete", "definition_id")).
		Delete(p+"/{definition_id}", w.DeleteTaskDefinitionV1TaskDefinitionsDefinitionIdDelete)
	clientChain(r, e, errs, request{pathUUIDs: id, body: taskDefRunBody, optionalBody: true}).
		Post(p+"/{definition_id}/run", w.RunTaskDefinitionV1TaskDefinitionsDefinitionIdRunPost)
}

func mapTaskDefError(err error) (*httpx.Error, bool) {
	var (
		nf    *service.TaskDefNotFoundError
		inv   *service.TaskDefInvalidError
		inUse *service.TaskDefInUseError
	)
	switch {
	case errors.As(err, &nf):
		return httpx.HTTPError(http.StatusNotFound, nf.Error()), true
	case errors.As(err, &inv):
		return httpx.HTTPError(http.StatusBadRequest, inv.Msg), true
	case errors.As(err, &inUse):
		return httpx.HTTPError(http.StatusConflict, inUse.Error()), true
	}
	return nil, false
}
