package service

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/openapispec"
)

// BundleOpenAPIs is what a bundle deploy reads and writes of OpenAPI
// connections; S is the service in force. A workspace secret a connection
// names is read when the deploy writes it: the connection stores its own
// copy, as a value entered in the form is stored.
type BundleOpenAPIs struct{ S func() *Service }

var _ catalogapi.BundleOpenAPIs = BundleOpenAPIs{}

func openAPIRefusal(err error) error {
	var invalid *domain.Invalid
	if errors.As(err, &invalid) {
		return &catalogapi.BundleRefusal{Msg: invalid.Msg}
	}
	return bundleRefusal(err)
}

func (b BundleOpenAPIs) ConnectionName(ctx context.Context, c authn.Caller, id string) (string, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return "", false, nil
	}
	v, err := b.S().GetConnection(ctx, c, u)
	var nf *domain.NotFound
	switch {
	case errors.As(err, &nf):
		return "", false, nil
	case err != nil:
		return "", false, err
	}
	return v.Connection.Name, true, nil
}

func (BundleOpenAPIs) HeaderIsSecret(name string) bool {
	return !safeHeaders()[strings.ToLower(strings.TrimSpace(name))]
}

// secretValues are the values of the workspace secrets params name, each
// one the caller may wire into a connection.
func (b BundleOpenAPIs) secretValues(ctx context.Context, c authn.Caller, params ...[]catalogapi.BundleOpenAPIParam) (map[string]string, error) {
	s := b.S()
	names := map[string]string{}
	for _, ps := range params {
		for _, p := range ps {
			if p.SecretName != nil { // pragma: allowlist secret
				names[*p.SecretName] = *p.SecretName
			}
		}
	}
	if _, err := s.secretRefs(ctx, c, names); err != nil {
		return nil, openAPIRefusal(err)
	}
	out := map[string]string{}
	err := s.read(ctx, c, func(sess db.Session) error {
		m := s.d.Secrets.Manager(sess, c.UserID)
		for name := range names {
			v, err := m.Get(ctx, name)
			if errors.Is(err, ksecrets.ErrNotFound) || (err == nil && v == "") {
				return &catalogapi.BundleRefusal{Msg: "Secret '" + name + "' has no value"}
			}
			if err != nil {
				return err
			}
			out[name] = v
		}
		return nil
	})
	return out, err
}

// paramValue is p's value: its secret's, the stored one when kept, else its own.
func paramValue(p catalogapi.BundleOpenAPIParam, secrets, stored map[string]string) (string, bool) {
	switch {
	case p.SecretName != nil: // pragma: allowlist secret
		return secrets[*p.SecretName], true
	case p.Keep:
		v, ok := stored[p.Name]
		return v, ok
	}
	return p.Value, true
}

type openAPIInput struct {
	headers []HeaderIn
	query   []QueryIn
	vars    []VarIn
}

func openAPIInputOf(spec catalogapi.BundleOpenAPISpec, secrets map[string]string, stored openAPIStored) openAPIInput {
	var in openAPIInput
	for _, p := range spec.Headers {
		if v, ok := paramValue(p, secrets, stored.headers); ok {
			in.headers = append(in.headers, HeaderIn{Name: p.Name, Value: v})
		}
	}
	for _, p := range spec.Query {
		if v, ok := paramValue(p, secrets, stored.query); ok {
			in.query = append(in.query, QueryIn{Name: p.Name, Secret: p.Secret, Value: v})
		}
	}
	for _, p := range spec.Variables {
		if v, ok := paramValue(p, secrets, stored.vars); ok {
			in.vars = append(in.vars, VarIn{Name: p.Name, Value: v})
		}
	}
	return in
}

// openAPIStored are the values a connection holds, by header, query parameter and variable name.
type openAPIStored struct{ headers, query, vars map[string]string }

func (b BundleOpenAPIs) stored(ctx context.Context, c authn.Caller, conn domain.Connection) (openAPIStored, error) {
	out := openAPIStored{headers: map[string]string{}, query: map[string]string{}, vars: map[string]string{}}
	var names []string
	for _, h := range conn.CustomHeaders {
		if h.Secret {
			names = append(names, domain.SecretHeaderKey(conn.ID, h.Name))
		} else if h.Value != nil {
			out.headers[h.Name] = *h.Value
		}
	}
	for _, q := range conn.CustomQuery {
		if q.Secret {
			names = append(names, domain.SecretQueryKey(conn.ID, q.Name))
		} else if q.Value != nil {
			out.query[q.Name] = *q.Value
		}
	}
	for _, v := range conn.URLVariables {
		names = append(names, domain.SecretURLVarKey(conn.ID, v))
	}
	values, err := b.S().connectionSecretValues(ctx, c.Workspace, c.UserID, conn, names)
	if err != nil {
		return out, err
	}
	for _, h := range conn.CustomHeaders {
		if v, ok := values[domain.SecretHeaderKey(conn.ID, h.Name)]; ok && h.Secret {
			out.headers[h.Name] = v
		}
	}
	for _, q := range conn.CustomQuery {
		if v, ok := values[domain.SecretQueryKey(conn.ID, q.Name)]; ok && q.Secret {
			out.query[q.Name] = v
		}
	}
	for _, name := range conn.URLVariables {
		if v, ok := values[domain.SecretURLVarKey(conn.ID, name)]; ok {
			out.vars[name] = v
		}
	}
	return out, nil
}

func (b BundleOpenAPIs) OpenAPIProblem(ctx context.Context, c authn.Caller, spec catalogapi.BundleOpenAPISpec) (string, error) {
	s := b.S()
	vars := make([]string, len(spec.Variables))
	for i, v := range spec.Variables {
		vars[i] = v.Name
	}
	check := func() error {
		if err := openapispec.CheckURLVariables(spec.BaseURL, vars); err != nil {
			return invalid(err)
		}
		if err := s.checkURL(ctx, spec.BaseURL); err != nil {
			return err
		}
		if spec.SpecURL != nil {
			if err := s.checkURL(ctx, *spec.SpecURL); err != nil {
				return err
			}
		}
		if spec.Spec != nil {
			query := map[string]bool{}
			for _, q := range spec.Query {
				query[q.Name] = true
			}
			if _, err := openapispec.ParseSpec(spec.Spec, query); err != nil {
				return invalid(err)
			}
		}
		names := map[string]string{}
		for _, ps := range [][]catalogapi.BundleOpenAPIParam{spec.Headers, spec.Query, spec.Variables} {
			for _, p := range ps {
				if p.SecretName != nil { // pragma: allowlist secret
					names[*p.SecretName] = *p.SecretName
				}
			}
		}
		_, err := s.secretRefs(ctx, c, names)
		return err
	}
	var r *catalogapi.BundleRefusal
	if err := openAPIRefusal(check()); errors.As(err, &r) {
		return r.Msg, nil
	} else if err != nil {
		return "", err
	}
	return "", nil
}

func (b BundleOpenAPIs) CreateOpenAPI(ctx context.Context, c authn.Caller, spec catalogapi.BundleOpenAPISpec) (string, error) {
	secrets, err := b.secretValues(ctx, c, spec.Headers, spec.Query, spec.Variables)
	if err != nil {
		return "", err
	}
	in := openAPIInputOf(spec, secrets, openAPIStored{})
	v, err := b.S().CreateConnection(ctx, c, ConnectionCreate{Name: spec.Name, BaseURL: spec.BaseURL, Description: spec.Description,
		SpecURL: spec.SpecURL, SpecContent: spec.Spec, Headers: in.headers, Query: in.query, URLVariables: in.vars}, nil)
	if err != nil {
		return "", openAPIRefusal(err)
	}
	return v.Connection.ID, nil
}

// UpdateOpenAPI writes every field of spec over the connection, a kept value
// as it is stored, then reads its spec_url again for the tools it serves now.
func (b BundleOpenAPIs) UpdateOpenAPI(ctx context.Context, c authn.Caller, id string, spec catalogapi.BundleOpenAPISpec) error {
	s := b.S()
	u, err := uuid.Parse(id)
	if err != nil {
		return catalogapi.ErrBundleEntityGone
	}
	if err := s.Require(ctx, c, "edit", "openapi_connection", id); err != nil {
		return err
	}
	var conn domain.Connection
	err = s.read(ctx, c, func(sess db.Session) error {
		got, ok, err := s.d.OpenAPIWrites.Full(ctx, sess, u)
		if err == nil && !ok {
			err = catalogapi.ErrBundleEntityGone
		}
		conn = got
		return err
	})
	if err != nil {
		return err
	}
	stored, err := b.stored(ctx, c, conn)
	if err != nil {
		return err
	}
	secrets, err := b.secretValues(ctx, c, spec.Headers, spec.Query, spec.Variables)
	if err != nil {
		return err
	}
	in := openAPIInputOf(spec, secrets, stored)
	_, err = s.UpdateConnection(ctx, c, u, ConnectionPatch{NameSet: true, Name: spec.Name, DescriptionSet: true, Description: spec.Description,
		BaseURLSet: true, BaseURL: spec.BaseURL, SpecURLSet: true, SpecURL: spec.SpecURL, SpecContentSet: true, SpecContent: spec.Spec,
		HeadersSet: true, Headers: in.headers, QuerySet: true, Query: in.query, URLVariablesSet: true, URLVariables: in.vars})
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return catalogapi.ErrBundleEntityGone
	}
	if err != nil {
		return openAPIRefusal(err)
	}
	if spec.Spec == nil && spec.SpecURL != nil {
		_, err = s.DiscoverTools(ctx, c, u)
	}
	return openAPIRefusal(err)
}

func (b BundleOpenAPIs) DeleteOpenAPI(ctx context.Context, c authn.Caller, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return b.S().DeleteConnection(ctx, c, u)
}
