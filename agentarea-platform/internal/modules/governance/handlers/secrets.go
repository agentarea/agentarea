package handlers

import (
	"context"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/service"
)

// MaxSecretDescription is the description bound of SecretCreate and SecretDescriptionUpdate.
const MaxSecretDescription = 1000

type secretBody struct {
	name, value string
	description *string
}

// secretCreateBody is SecretCreate (extra="forbid").
func secretCreateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	if x, present := o.Get("name"); !present {
		c.Errs = append(c.Errs, httpx.Missing(body("name")...))
	} else {
		in.name, _ = c.Str(x, body("name"), 0, 0)
	}
	if x, present := o.Get("value"); !present {
		c.Errs = append(c.Errs, httpx.Missing(body("value")...))
	} else {
		in.value, _ = c.Str(x, body("value"), 1, 0)
	}
	x, present := o.Get("description")
	in.description = c.OptStr(x, present, body("description"), 0, MaxSecretDescription)
	c.Extra(o, []string{"name", "value", "description"}, body())
	*errs = append(*errs, c.Errs...)
}

// secretDescriptionBody is SecretDescriptionUpdate (extra="forbid").
func secretDescriptionBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	x, present := o.Get("description")
	in.description = c.OptStr(x, present, body("description"), 0, MaxSecretDescription)
	c.Extra(o, []string{"description"}, body())
	*errs = append(*errs, c.Errs...)
}

// secretValueBody is SecretValueUpdate (extra="forbid").
func secretValueBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	if x, present := o.Get("value"); !present {
		c.Errs = append(c.Errs, httpx.Missing(body("value")...))
	} else {
		in.value, _ = c.Str(x, body("value"), 1, 0)
	}
	c.Extra(o, []string{"value"}, body())
	*errs = append(*errs, c.Errs...)
}

// secretJSON is SecretResponse.
func secretJSON(v service.SecretView) wirejson.Object {
	s := v.Secret
	used := make([]any, len(v.UsedBy))
	for i, c := range v.UsedBy {
		used[i] = wirejson.Object{
			{Key: "consumer_type", Value: c.ConsumerType},
			{Key: "consumer_id", Value: c.ConsumerID},
			{Key: "field", Value: c.Field},
		}
	}
	var owner any
	if s.OwnerType != nil && s.OwnerID != nil {
		var field any
		if f := secrets.ManagedField(s.Name); f != "" {
			field = f
		}
		owner = wirejson.Object{
			{Key: "type", Value: *s.OwnerType},
			{Key: "id", Value: *s.OwnerID},
			{Key: "name", Value: v.OwnerName},
			{Key: "field", Value: field},
		}
	}
	stamp := func(t interface{ IsZero() bool }, iso string) any {
		if t.IsZero() {
			return nil
		}
		return iso
	}
	return wirejson.Object{
		{Key: "id", Value: s.ID},
		{Key: "name", Value: s.Name},
		{Key: "description", Value: s.Description},
		{Key: "created_at", Value: stamp(s.CreatedAt, utcISO(s.CreatedAt))},
		{Key: "updated_at", Value: stamp(s.UpdatedAt, utcISO(s.UpdatedAt))},
		{Key: "used_by", Value: used},
		{Key: "owner", Value: owner},
	}
}

func secretID(ctx context.Context) string { return inputFrom(ctx).path["secret_id"] }

func (s *Server) ListSecretsV1SecretsGet(ctx context.Context, _ gen.ListSecretsV1SecretsGetRequestObject) (gen.ListSecretsV1SecretsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	views, err := s.svc.ListSecrets(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(views))
	for i, v := range views {
		out[i] = secretJSON(v)
	}
	return ok(out), nil
}

func (s *Server) CreateSecretV1SecretsPost(ctx context.Context, _ gen.CreateSecretV1SecretsPostRequestObject) (gen.CreateSecretV1SecretsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	v, err := s.svc.CreateSecret(ctx, c, in.name, in.value, in.description)
	if err != nil {
		return nil, err
	}
	return created(secretJSON(v)), nil
}

func (s *Server) GetSecretV1SecretsSecretIdGet(ctx context.Context, _ gen.GetSecretV1SecretsSecretIdGetRequestObject) (gen.GetSecretV1SecretsSecretIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.GetSecret(ctx, c, secretID(ctx))
	if err != nil {
		return nil, err
	}
	return ok(secretJSON(v)), nil
}

func (s *Server) UpdateSecretDescriptionV1SecretsSecretIdPatch(ctx context.Context, _ gen.UpdateSecretDescriptionV1SecretsSecretIdPatchRequestObject) (gen.UpdateSecretDescriptionV1SecretsSecretIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.UpdateSecretDescription(ctx, c, secretID(ctx), inputFrom(ctx).description)
	if err != nil {
		return nil, err
	}
	return ok(secretJSON(v)), nil
}

func (s *Server) RotateSecretV1SecretsSecretIdValuePut(ctx context.Context, _ gen.RotateSecretV1SecretsSecretIdValuePutRequestObject) (gen.RotateSecretV1SecretsSecretIdValuePutResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.RotateSecret(ctx, c, secretID(ctx), inputFrom(ctx).value)
	if err != nil {
		return nil, err
	}
	return ok(secretJSON(v)), nil
}

func (s *Server) DeleteSecretV1SecretsSecretIdDelete(ctx context.Context, _ gen.DeleteSecretV1SecretsSecretIdDeleteRequestObject) (gen.DeleteSecretV1SecretsSecretIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteSecret(ctx, c, secretID(ctx)); err != nil {
		return nil, err
	}
	return noContent(), nil
}
