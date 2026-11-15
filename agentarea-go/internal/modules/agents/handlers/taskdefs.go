package handlers

import (
	"context"
	"net/http"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

const (
	taskDefMaxListLimit   = 1000
	taskDefMaxName        = 255
	taskDefMaxDescription = 20000
)

// taskDefInput is what a task definition route validated to.
type taskDefInput struct {
	agentID    *uuid.UUID
	limit      int32
	create     service.TaskDefCreate
	patch      service.TaskDefPatch
	parameters wirejson.Object
}

func taskDefListQuery(q map[string][]string, in *input, errs *[]httpx.FieldError) {
	ti := taskDefInput{limit: 100}
	if v, ok := clientLast(q, "agent_id"); ok {
		if id, fe := httpx.ValidateUUID(v, "query", "agent_id"); fe != nil {
			*errs = append(*errs, *fe)
		} else {
			u := uuid.MustParse(id)
			ti.agentID = &u
		}
	}
	if v, ok := clientLast(q, "limit"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: taskDefMaxListLimit, HasLe: true}, "query", "limit")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			ti.limit = int32(n)
		}
	}
	in.area = ti
}

// taskDefText is a str field with _require_text: bounds first, then stripped and refused when blank.
func taskDefText(o wirejson.Object, key string, maxLen int, nullable bool, errs *[]httpx.FieldError) (*string, bool) {
	v, set := str(o, key, 1, maxLen, nullable, errs)
	if v == nil {
		return nil, set
	}
	s := pyStrip(*v)
	if s == "" {
		*errs = append(*errs, httpx.ValueError("must not be blank", "body", key))
		return nil, set
	}
	return &s, set
}

// taskDefParameters is a dict[str, Any] parameters field and its validators; ok when it validated.
func taskDefParameters(o wirejson.Object, nullable bool, errs *[]httpx.FieldError) (params wirejson.Object, set, ok bool) {
	v, present := o.Get("parameters")
	if !present {
		return nil, false, true
	}
	if v == nil && nullable {
		return nil, true, true
	}
	p, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.DictType("body", "parameters"))
		return nil, true, false
	}
	keys := make([]string, len(p))
	for i, m := range p {
		keys[i] = m.Key
	}
	if msg := domain.TaskDefCheckParameters(keys, p.Get); msg != "" {
		*errs = append(*errs, httpx.ValueError(msg, "body", "parameters"))
		return nil, true, false
	}
	return p, true, true
}

func taskDefAgentID(o wirejson.Object, nullable bool, errs *[]httpx.FieldError) (*uuid.UUID, bool) {
	v, present := o.Get("agent_id")
	if !present {
		return nil, false
	}
	if v == nil && !nullable {
		*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", "agent_id"}, Msg: "UUID input should be a string, bytes or UUID object"})
		return nil, true
	}
	id, set := uuidField(o, "agent_id", errs)
	if id == nil {
		return nil, set
	}
	u := uuid.MustParse(*id)
	return &u, set
}

func taskDefStored(p wirejson.Object) ([]byte, error) {
	return wirejson.Marshal(p, wirejson.Dumps)
}

// taskDefCreateBody is TaskDefinitionCreate (extra="forbid").
func taskDefCreateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var ti taskDefInput
	if name, set := taskDefText(o, "name", taskDefMaxName, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "name"))
	} else if name != nil {
		ti.create.Name = *name
	}
	if d, set := taskDefText(o, "description", taskDefMaxDescription, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "description"))
	} else if d != nil {
		ti.create.Description = *d
	}
	if id, set := taskDefAgentID(o, false, errs); !set {
		*errs = append(*errs, httpx.Missing("body", "agent_id"))
	} else if id != nil {
		ti.create.AgentID = *id
	}
	if p, _, ok := taskDefParameters(o, false, errs); ok {
		if p == nil {
			p = wirejson.Object{}
		}
		raw, err := taskDefStored(p)
		if err != nil {
			*errs = append(*errs, httpx.DictType("body", "parameters"))
		}
		ti.create.Parameters = raw
	}
	extraForbidden(o, []string{"name", "description", "agent_id", "parameters"}, errs)
	in.area = ti
}

// taskDefUpdateBody is TaskDefinitionUpdate (extra="forbid"); a field may be left out, never set to null.
func taskDefUpdateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var ti taskDefInput
	if !clientNotNull(o, "name", errs) {
		ti.patch.Name, _ = taskDefText(o, "name", taskDefMaxName, false, errs)
	}
	if !clientNotNull(o, "description", errs) {
		ti.patch.Description, _ = taskDefText(o, "description", taskDefMaxDescription, false, errs)
	}
	if !clientNotNull(o, "agent_id", errs) {
		ti.patch.AgentID, _ = taskDefAgentID(o, false, errs)
	}
	if clientNotNull(o, "parameters", errs) {
		extraForbidden(o, []string{"name", "description", "agent_id", "parameters"}, errs)
		in.area = ti
		return
	}
	if p, _, ok := taskDefParameters(o, false, errs); ok && p != nil {
		raw, err := taskDefStored(p)
		if err != nil {
			*errs = append(*errs, httpx.DictType("body", "parameters"))
		}
		ti.patch.Parameters = raw
	}
	extraForbidden(o, []string{"name", "description", "agent_id", "parameters"}, errs)
	in.area = ti
}

// taskDefRunBody is TaskDefinitionRun | None (extra="forbid").
func taskDefRunBody(v any, in *input, errs *[]httpx.FieldError) {
	if v == nil {
		return
	}
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var ti taskDefInput
	if p, _, ok := taskDefParameters(o, true, errs); ok {
		ti.parameters = p
	}
	extraForbidden(o, []string{"parameters"}, errs)
	in.area = ti
}

// taskDefJSON is TaskDefinitionResponse.
func taskDefJSON(d store.TaskDefRow) (wirejson.Object, error) {
	var params any = wirejson.Object{}
	if len(d.Parameters) > 0 {
		v, err := wirejson.Unmarshal(d.Parameters)
		if err != nil {
			return nil, err
		}
		if v != nil {
			params = v
		}
	}
	return wirejson.Object{
		{Key: "id", Value: d.ID.String()}, {Key: "name", Value: d.Name}, {Key: "description", Value: d.Description},
		{Key: "agent_id", Value: d.AgentID.String()}, {Key: "parameters", Value: params}, {Key: "created_by", Value: d.CreatedBy},
		{Key: "created_at", Value: domain.TaskDefISOZ(d.CreatedAt)}, {Key: "updated_at", Value: domain.TaskDefISOZ(d.UpdatedAt)},
	}, nil
}

func taskDefResponse(status int, d store.TaskDefRow, err error) (response, error) {
	if err != nil {
		return response{}, err
	}
	body, err := taskDefJSON(d)
	if err != nil {
		return response{}, err
	}
	return response{status: status, body: body}, nil
}

func (s *Server) ListTaskDefinitionsV1TaskDefinitionsGet(ctx context.Context, _ gen.ListTaskDefinitionsV1TaskDefinitionsGetRequestObject) (gen.ListTaskDefinitionsV1TaskDefinitionsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := areaInput[taskDefInput](ctx)
	rows, err := s.ext.TaskDefs.List(ctx, c, in.agentID, in.limit)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(rows))
	for i, d := range rows {
		if out[i], err = taskDefJSON(d); err != nil {
			return nil, err
		}
	}
	return ok(out), nil
}

func (s *Server) CreateTaskDefinitionV1TaskDefinitionsPost(ctx context.Context, _ gen.CreateTaskDefinitionV1TaskDefinitionsPostRequestObject) (gen.CreateTaskDefinitionV1TaskDefinitionsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	d, err := s.ext.TaskDefs.Create(ctx, c, areaInput[taskDefInput](ctx).create)
	return taskDefResponse(http.StatusCreated, d, err)
}

func (s *Server) GetTaskDefinitionV1TaskDefinitionsDefinitionIdGet(ctx context.Context, rq gen.GetTaskDefinitionV1TaskDefinitionsDefinitionIdGetRequestObject) (gen.GetTaskDefinitionV1TaskDefinitionsDefinitionIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	d, err := s.ext.TaskDefs.Get(ctx, c, rq.DefinitionId)
	return taskDefResponse(http.StatusOK, d, err)
}

func (s *Server) UpdateTaskDefinitionV1TaskDefinitionsDefinitionIdPut(ctx context.Context, rq gen.UpdateTaskDefinitionV1TaskDefinitionsDefinitionIdPutRequestObject) (gen.UpdateTaskDefinitionV1TaskDefinitionsDefinitionIdPutResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	d, err := s.ext.TaskDefs.Update(ctx, c, rq.DefinitionId, areaInput[taskDefInput](ctx).patch)
	return taskDefResponse(http.StatusOK, d, err)
}

func (s *Server) DeleteTaskDefinitionV1TaskDefinitionsDefinitionIdDelete(ctx context.Context, rq gen.DeleteTaskDefinitionV1TaskDefinitionsDefinitionIdDeleteRequestObject) (gen.DeleteTaskDefinitionV1TaskDefinitionsDefinitionIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	deleted, err := s.ext.TaskDefs.Delete(ctx, c, rq.DefinitionId)
	if err != nil {
		return nil, err
	}
	if !deleted {
		return nil, httpx.HTTPError(http.StatusNotFound, "Task definition "+rq.DefinitionId.String()+" not found")
	}
	return noContent(), nil
}

func (s *Server) RunTaskDefinitionV1TaskDefinitionsDefinitionIdRunPost(ctx context.Context, rq gen.RunTaskDefinitionV1TaskDefinitionsDefinitionIdRunPostRequestObject) (gen.RunTaskDefinitionV1TaskDefinitionsDefinitionIdRunPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	body, err := s.ext.TaskDefs.Run(ctx, c, rq.DefinitionId, areaInput[taskDefInput](ctx).parameters, "api")
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: body}, nil
}
