package handlers

import (
	"context"
	"errors"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

type collectionInput struct {
	name        *string
	description service.Set[string]
	skillID     string
}

func collectionBody(requireName bool) func(v any, in *input, errs *[]httpx.FieldError) {
	return func(v any, in *input, errs *[]httpx.FieldError) {
		o, ok := model(v, errs)
		if !ok {
			return
		}
		name, set := str(o, "name", 1, maxName, !requireName, errs)
		if !set && requireName {
			*errs = append(*errs, httpx.Missing("body", "name"))
		}
		in.collect.name = name
		in.collect.description.Value, in.collect.description.Set = str(o, "description", 0, 0, true, errs)
	}
}

func addSkillBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	id, set := uuidField(o, "skill_id", errs)
	switch {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "skill_id"))
	case id == nil:
		*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", "skill_id"}, Msg: "UUID input should be a string, bytes or UUID object"})
	default:
		in.collect.skillID = *id
	}
}

func mapCollectionError(err error) (*httpx.Error, bool) {
	switch {
	case errors.Is(err, service.ErrCollectionNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Collection not found"), true
	case errors.Is(err, service.ErrSkillNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Skill not found"), true
	}
	return nil, false
}

func summaryJSON(c service.CollectionSummary) wirejson.Object {
	return wirejson.Object{{Key: "id", Value: c.ID}, {Key: "name", Value: c.Name}, {Key: "description", Value: orNil(c.Description)},
		{Key: "skill_count", Value: c.SkillCount}}
}

func (s *Server) ListCollectionsV1SkillCollectionsGet(ctx context.Context, _ gen.ListCollectionsV1SkillCollectionsGetRequestObject) (gen.ListCollectionsV1SkillCollectionsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	cs, err := s.svc.ListCollections(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(cs))
	for i, x := range cs {
		out[i] = summaryJSON(x)
	}
	return ok(out), nil
}

func (s *Server) CreateCollectionV1SkillCollectionsPost(ctx context.Context, _ gen.CreateCollectionV1SkillCollectionsPostRequestObject) (gen.CreateCollectionV1SkillCollectionsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx).collect
	x, err := s.svc.CreateCollection(ctx, c, *in.name, in.description.Value)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: summaryJSON(x)}, nil
}

func (s *Server) GetCollectionV1SkillCollectionsCollectionIdGet(ctx context.Context, rq gen.GetCollectionV1SkillCollectionsCollectionIdGetRequestObject) (gen.GetCollectionV1SkillCollectionsCollectionIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	d, err := s.svc.GetCollection(ctx, c, rq.CollectionId)
	if err != nil {
		return nil, err
	}
	skills := make([]any, len(d.Skills))
	for i, sk := range d.Skills {
		skills[i] = wirejson.Object{{Key: "id", Value: sk.ID}, {Key: "name", Value: sk.Name}}
	}
	return ok(wirejson.Object{{Key: "id", Value: d.ID}, {Key: "name", Value: d.Name},
		{Key: "description", Value: orNil(d.Description)}, {Key: "skills", Value: skills}}), nil
}

func (s *Server) UpdateCollectionV1SkillCollectionsCollectionIdPut(ctx context.Context, rq gen.UpdateCollectionV1SkillCollectionsCollectionIdPutRequestObject) (gen.UpdateCollectionV1SkillCollectionsCollectionIdPutResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx).collect
	x, err := s.svc.UpdateCollection(ctx, c, rq.CollectionId, in.name, in.description)
	if err != nil {
		return nil, err
	}
	return ok(summaryJSON(x)), nil
}

func (s *Server) DeleteCollectionV1SkillCollectionsCollectionIdDelete(ctx context.Context, rq gen.DeleteCollectionV1SkillCollectionsCollectionIdDeleteRequestObject) (gen.DeleteCollectionV1SkillCollectionsCollectionIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteCollection(ctx, c, rq.CollectionId); err != nil {
		return nil, err
	}
	return noContent(), nil
}

func (s *Server) AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPost(ctx context.Context, rq gen.AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostRequestObject) (gen.AddSkillToCollectionV1SkillCollectionsCollectionIdSkillsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.AddCollectionSkill(ctx, c, rq.CollectionId, mustUUID(inputFrom(ctx).collect.skillID)); err != nil {
		return nil, err
	}
	return noContent(), nil
}

func (s *Server) RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDelete(ctx context.Context, rq gen.RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteRequestObject) (gen.RemoveSkillFromCollectionV1SkillCollectionsCollectionIdSkillsSkillIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.RemoveCollectionSkill(ctx, c, rq.CollectionId, rq.SkillId); err != nil {
		return nil, err
	}
	return noContent(), nil
}
