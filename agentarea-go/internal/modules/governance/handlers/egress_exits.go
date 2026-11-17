package handlers

import (
	"context"
	"net/http"
	"strings"
	"unicode"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/service"
)

// MaxCredentialBytes is MAX_CREDENTIAL_BYTES: socks5 carries each in one length byte.
const MaxCredentialBytes = 255

// egressGate is the router dependency _deployment_has_egress_exits: without
// the egress_exits extension every route is a 404 before its parameters are read.
func egressGate(errs *httpx.Errors, enforced bool) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		if enforced {
			return next
		}
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			errs.Write(w, r, egressUnavailable())
		})
	}
}

func egressUnavailable() error { return httpx.HTTPError(http.StatusNotFound, EgressDetail) }

// egressRequires is route_authz.requires(permission, "egress_exit",
// id_param="exit_id"): before the route's own validation, so a refusal comes
// before a 422 about the body.
func egressRequires(s *Server, errs *httpx.Errors, permission string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			id, err := uuid.Parse(chi.URLParam(r, "exit_id"))
			if err != nil {
				errs.Write(w, r, httpx.Validation(httpx.FieldError{Type: "uuid_parsing", Loc: []any{"path", "exit_id"}, Msg: "Input should be a valid UUID"}))
				return
			}
			c, err := caller(r.Context())
			if err == nil {
				err = s.svc.RequireOnEgressExit(r.Context(), c, permission, id.String())
			}
			if err != nil {
				errs.Write(w, r, err)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

type egressBody struct {
	exitNew   service.EgressExitNew
	exitPatch service.EgressExitPatch
}

// pyStrip is str.strip(): Unicode whitespace and the ASCII separators.
func pyStrip(s string) string {
	return strings.TrimFunc(s, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) })
}

func upstream(c *api.Checker, v any) (string, bool) {
	s, ok := c.Str(v, body("upstream_url"), 0, 512)
	if !ok {
		return "", false
	}
	u, err := domain.ValidateUpstreamURL(s)
	if err != nil {
		c.Errs = append(c.Errs, httpx.ValueError(err.Error(), body("upstream_url")...))
		return "", false
	}
	return u, true
}

func optUUID(c *api.Checker, v any, key string) (*string, bool) {
	if v == nil {
		return nil, true
	}
	s, isStr := v.(string)
	if !isStr {
		c.Errs = append(c.Errs, httpx.FieldError{Type: "uuid_type", Loc: body(key), Msg: "UUID input should be a string, bytes or UUID object"})
		return nil, false
	}
	id, fe := httpx.ValidateUUID(s, body(key)...)
	if fe != nil {
		c.Errs = append(c.Errs, *fe)
		return nil, false
	}
	return &id, true
}

// egressCreateBody is EgressExitCreate (extra="forbid"): field validators,
// then the credential check over the whole model at ("body",).
func egressCreateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	n := &in.exitNew
	if x, present := o.Get("name"); !present {
		c.Errs = append(c.Errs, httpx.Missing(body("name")...))
	} else if s, ok := c.Str(x, body("name"), 1, 255); ok {
		if n.Name = pyStrip(s); n.Name == "" {
			c.Errs = append(c.Errs, httpx.ValueError("name cannot be empty or whitespace", body("name")...))
		}
	}
	x, present := o.Get("description")
	n.Description = c.OptStr(x, present, body("description"), 0, 0)
	if x, present := o.Get("upstream_url"); !present {
		c.Errs = append(c.Errs, httpx.Missing(body("upstream_url")...))
	} else {
		n.UpstreamURL, _ = upstream(&c, x)
	}
	x, present = o.Get("username")
	n.Username = c.OptStr(x, present, body("username"), 0, MaxCredentialBytes)
	if x, present := o.Get("password_secret_id"); present {
		n.PasswordSecretID, _ = optUUID(&c, x, "password_secret_id")
	}
	if x, present := o.Get("allow_plaintext_credentials"); present {
		n.AllowPlaintextCredentials, _ = c.Bool(x, body("allow_plaintext_credentials"))
	}
	c.Extra(o, []string{"name", "description", "upstream_url", "username", "password_secret_id", "allow_plaintext_credentials"}, body())
	if len(c.Errs) == 0 {
		if msgs := domain.CredentialErrors(&n.UpstreamURL, n.Username, n.PasswordSecretID, n.AllowPlaintextCredentials); len(msgs) > 0 {
			c.Errs = append(c.Errs, httpx.ValueError(strings.Join(msgs, "; "), body()...))
		}
	}
	*errs = append(*errs, c.Errs...)
}

// egressUpdateBody is EgressExitUpdate (extra="forbid"): only the sent
// fields, null kept as null.
func egressUpdateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var c api.Checker
	p := service.EgressExitPatch{}
	for _, f := range []struct {
		key    string
		maxLen int
		minLen int
	}{{"name", 255, 1}, {"description", 0, 0}, {"username", MaxCredentialBytes, 0}} {
		if x, present := o.Get(f.key); present {
			if s := c.OptStr(x, true, body(f.key), f.minLen, f.maxLen); s != nil || x == nil {
				p[f.key] = s
			}
		}
	}
	if x, present := o.Get("upstream_url"); present {
		if x == nil {
			p["upstream_url"] = (*string)(nil)
		} else if u, ok := upstream(&c, x); ok {
			p["upstream_url"] = &u
		}
	}
	if x, present := o.Get("password_secret_id"); present {
		if id, ok := optUUID(&c, x, "password_secret_id"); ok {
			p["password_secret_id"] = id
		}
	}
	if x, present := o.Get("allow_plaintext_credentials"); present {
		if b := c.OptBool(x, true, body("allow_plaintext_credentials")); b != nil || x == nil {
			p["allow_plaintext_credentials"] = b
		}
	}
	c.Extra(o, []string{"name", "description", "upstream_url", "username", "password_secret_id", "allow_plaintext_credentials"}, body())
	in.exitPatch = p
	*errs = append(*errs, c.Errs...)
}

// egressExitJSON is EgressExitResponse.
func egressExitJSON(e domain.EgressExit) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: e.ID},
		{Key: "name", Value: e.Name},
		{Key: "description", Value: e.Description},
		{Key: "upstream_url", Value: e.UpstreamURL},
		{Key: "username", Value: e.Username},
		{Key: "password_secret_id", Value: e.PasswordSecretID},
		{Key: "via", Value: e.Via},
		{Key: "allow_plaintext_credentials", Value: e.AllowPlaintextCredentials},
		{Key: "managed_by", Value: e.ManagedBy},
		{Key: "created_by", Value: e.CreatedBy},
		{Key: "created_at", Value: utcISO(e.CreatedAt)},
		{Key: "updated_at", Value: utcISO(e.UpdatedAt)},
	}
}

func exitID(ctx context.Context) uuid.UUID { return uuid.MustParse(inputFrom(ctx).path["exit_id"]) }

func (s *Server) ListEgressExitsV1EgressExitsGet(ctx context.Context, _ gen.ListEgressExitsV1EgressExitsGetRequestObject) (gen.ListEgressExitsV1EgressExitsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	exits, err := s.svc.ListEgressExits(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(exits))
	for i, e := range exits {
		out[i] = egressExitJSON(e)
	}
	return ok(out), nil
}

func (s *Server) CreateEgressExitV1EgressExitsPost(ctx context.Context, _ gen.CreateEgressExitV1EgressExitsPostRequestObject) (gen.CreateEgressExitV1EgressExitsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	e, err := s.svc.CreateEgressExit(ctx, c, inputFrom(ctx).exitNew)
	if err != nil {
		return nil, err
	}
	return created(egressExitJSON(e)), nil
}

func (s *Server) GetEgressExitV1EgressExitsExitIdGet(ctx context.Context, _ gen.GetEgressExitV1EgressExitsExitIdGetRequestObject) (gen.GetEgressExitV1EgressExitsExitIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	e, err := s.svc.GetEgressExit(ctx, c, exitID(ctx))
	if err != nil {
		return nil, err
	}
	return ok(egressExitJSON(e)), nil
}

func (s *Server) UpdateEgressExitV1EgressExitsExitIdPatch(ctx context.Context, _ gen.UpdateEgressExitV1EgressExitsExitIdPatchRequestObject) (gen.UpdateEgressExitV1EgressExitsExitIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	e, err := s.svc.UpdateEgressExit(ctx, c, exitID(ctx), inputFrom(ctx).exitPatch)
	if err != nil {
		return nil, err
	}
	return ok(egressExitJSON(e)), nil
}

func (s *Server) DeleteEgressExitV1EgressExitsExitIdDelete(ctx context.Context, _ gen.DeleteEgressExitV1EgressExitsExitIdDeleteRequestObject) (gen.DeleteEgressExitV1EgressExitsExitIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteEgressExit(ctx, c, exitID(ctx)); err != nil {
		return nil, err
	}
	return noContent(), nil
}
