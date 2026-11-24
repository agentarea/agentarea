package handlers

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
)

type global struct{}

func (global) Read(context.Context) (db.Querier, func(), error) { return nil, func() {}, nil }
func (global) Write(ctx context.Context, fn func(context.Context, db.Querier) error) error {
	return fn(ctx, nil)
}

type database struct{ db.Database }

func (database) Global() db.Global { return global{} }
func (database) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}
func (database) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type rows struct {
	service.Store
	keys    []domain.APIKey
	links   []domain.ExternalIdentity
	holders map[string]string
	owners  map[string]string
}

func (r *rows) GetWorkspace(_ context.Context, _ db.Querier, id string) (domain.Workspace, bool, error) {
	owner, ok := r.owners[id]
	return domain.Workspace{ID: id, Name: "Acme " + id, OwnerUserID: owner}, ok, nil
}

// members answers whether a user is a member of a workspace: "workspace:user".
type members map[string]bool

func (members) Read(context.Context, authz.Query) ([]authz.Tuple, error) { return nil, nil }
func (m members) Check(_ context.Context, subject, _, _, workspace string) (bool, error) {
	_, user, _ := strings.Cut(subject, ":")
	return m[workspace+":"+user], nil
}

func (r *rows) ExternalIdentityHolder(_ context.Context, _ db.Querier, _, id string) (string, bool, error) {
	u, ok := r.holders[id]
	return u, ok, nil
}

func (r *rows) InsertExternalIdentity(_ context.Context, _ db.Querier, userID string, a domain.MessengerAccount, _ string, now time.Time) (domain.ExternalIdentity, error) {
	r.holders[a.ExternalID] = userID
	return domain.ExternalIdentity{ID: "new", Provider: a.Provider, ExternalID: a.ExternalID, Username: &a.Username, DisplayName: &a.Name, CreatedAt: now}, nil
}

func (r *rows) ListAPIKeys(_ context.Context, _ db.Session, by *string, _ *uuid.UUID) ([]domain.APIKey, error) {
	var out []domain.APIKey
	for _, k := range r.keys {
		if by == nil || k.CreatedBy == *by {
			out = append(out, k)
		}
	}
	return out, nil
}

func (r *rows) ListExternalIdentities(context.Context, db.Querier, string) ([]domain.ExternalIdentity, error) {
	return r.links, nil
}

func (r *rows) RevokeExternalIdentity(context.Context, db.Querier, string, uuid.UUID, time.Time) (bool, error) {
	return false, nil
}

type codes struct{ offers map[string]domain.LinkOffer }

func (codes) Issue(context.Context, string) (string, error) { return "CODE", nil }

func (codes) Redeem(context.Context, string, string, string) (string, bool, error) {
	return "", false, nil
}

func (codes) Confirm(context.Context, string, string) (string, bool, error) { return "", false, nil }

func (codes) Offer(context.Context, domain.LinkOffer, time.Duration) (string, bool, error) {
	return "OFFER", true, nil
}

func (c codes) PeekOffer(_ context.Context, code string) (domain.LinkOffer, bool, error) {
	o, ok := c.offers[code]
	return o, ok, nil
}

func (c codes) TakeOffer(_ context.Context, code string) (domain.LinkOffer, bool, error) {
	o, ok := c.offers[code]
	delete(c.offers, code)
	return o, ok, nil
}

type noLogos struct{}

func (noLogos) Put(context.Context, string, io.Reader, int64, blob.PutOptions) error { return nil }
func (noLogos) Delete(context.Context, string) error                                 { return nil }
func (noLogos) PresignGet(context.Context, string, time.Duration) (blob.Presigned, error) {
	return blob.Presigned{}, nil
}

type nothing struct{ service.Resources }

func rest(t *testing.T, kind authn.CredentialKind, admin bool, d service.Deps) *httptest.Server {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	p := authn.Principal{UserID: "me", Credential: &authn.Credential{Kind: kind}, AdminWorkspaces: []string{}}
	if admin {
		p.AdminWorkspaces = []string{ws.ID()}
	}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), authn.Caller{Principal: p, Workspace: ws})))
			})
		},
		Principal: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(w, r.WithContext(authn.WithPrincipal(r.Context(), p)))
			})
		},
		Admin: func(context.Context) error {
			if admin {
				return nil
			}
			return authz.ErrNotWorkspaceAdmin
		},
	}
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError, func(err error) (*httpx.Error, bool) {
		var scopeErr *authn.ScopeRequiredError
		switch {
		case errors.Is(err, authz.ErrNotWorkspaceAdmin):
			return httpx.HTTPError(http.StatusForbidden, authz.NotAdminDetail), true
		case errors.As(err, &scopeErr):
			return httpx.Forbidden(scopeErr.Error()), true
		}
		return nil, false
	})
	if d.DB == nil {
		d.DB = database{}
	}
	if d.Store == nil {
		d.Store = &rows{}
	}
	r := chi.NewRouter()
	svc := service.New(d, nil)
	Mount(r, errs, edge, svc)
	MountRest(r, errs, edge, svc, Features{Logos: true, Explorer: true})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s
}

func do(t *testing.T, s *httptest.Server, method, path, contentType string, body io.Reader) (int, string) {
	t.Helper()
	req, err := http.NewRequest(method, s.URL+path, body)
	if err != nil {
		t.Fatal(err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(raw)
}

func jsonDo(t *testing.T, s *httptest.Server, method, path, body string) (int, string) {
	t.Helper()
	var rd io.Reader
	if body != "" {
		rd = strings.NewReader(body)
	}
	return do(t, s, method, path, "application/json", rd)
}

func TestRestValidationAndRefusals(t *testing.T) {
	session := rest(t, authn.KindSession, true, service.Deps{Resources: nothing{}})
	key := rest(t, authn.KindAPIKey, true, service.Deps{Resources: nothing{}})
	member := rest(t, authn.KindSession, false, service.Deps{Resources: nothing{}})
	long := strings.Repeat("x", 256)
	for _, c := range []struct {
		s                  *httptest.Server
		method, path, body string
		status             int
		want               string
	}{
		{session, "GET", "/v1/workspaces/acme/api-keys/?agent_id=x", "", 422, `"loc":["query","agent_id"]`},
		{session, "GET", "/v1/workspaces/acme/api-keys/nope", "", 422, `"loc":["path","token_id"]`},
		{key, "DELETE", "/v1/workspaces/acme/api-keys/nope", "", 403, "This credential cannot revoke API keys"},
		{session, "DELETE", "/v1/workspaces/acme/api-keys/nope", "", 422, `"type":"uuid_parsing"`},
		{session, "DELETE", "/v1/workspaces/acme/members/" + long, "", 422, `"type":"string_too_long"`},
		{member, "GET", "/v1/workspaces/acme/invitations", "", 403, authz.NotAdminDetail},
		{member, "DELETE", "/v1/workspaces/acme/invitations/nope", "", 403, authz.NotAdminDetail},
		{session, "DELETE", "/v1/workspaces/acme/invitations/nope", "", 422, `"loc":["path","invitation_id"]`},
		{session, "POST", "/v1/invitations/preview", `{}`, 422, `"loc":["body","token"]`},
		{key, "POST", "/v1/me/external-identities/telegram/link", `{"bot":"x"}`, 403, "This credential cannot link a messenger account"},
		{session, "POST", "/v1/me/external-identities/telegram/link", `{"bot":"bad-bot"}`, 422, `"type":"string_pattern_mismatch"`},
		{session, "POST", "/v1/me/external-identities/telegram/link", `{"bot":"good_bot"}`, 503, "Account linking needs the Redis broker"},
		{key, "DELETE", "/v1/me/external-identities/nope", "", 403, "This credential cannot unlink a messenger account"},
		{session, "DELETE", "/v1/me/external-identities/" + uuid.NewString(), "", 404, "No such linked account"},
		{session, "POST", "/v1/workspaces/acme/access-control/resolve", `{"subject_id":"User:me","resource_kind":"tool","resource_id":"x"}`, 422, `"type":"literal_error"`},
		{session, "POST", "/v1/workspaces/acme/access-control/check", `{"namespace":"Agent"}`, 422, `"loc":["body","subject_id"]`},
		{session, "POST", "/v1/workspaces/acme/access-control/relationships", `{"namespace":"Agent","object":"x","relation":"reader","subject_set":5}`, 422, `"type":"model_attributes_type"`},
		{session, "POST", "/v1/workspaces/acme/access-control/relationships", `{"namespace":"Agent","object":"x","relation":"reader","subject_set":{"namespace":"a"}}`, 422, `"loc":["body","subject_set","object"]`},
		{member, "POST", "/v1/workspaces/acme/access-control/check", `{"namespace":"Agent","object":"x","relation":"use","subject_id":"User:me"}`, 403, authz.NotAdminDetail},
		{member, "GET", "/v1/workspaces/acme/access-control/graph", "", 403, authz.NotAdminDetail},
		{member, "POST", "/v1/workspaces/acme/access-control/sync", "", 403, authz.NotAdminDetail},
		{member, "DELETE", "/v1/workspaces/acme/logo", "", 403, authz.NotAdminDetail},
	} {
		status, body := jsonDo(t, c.s, c.method, c.path, c.body)
		if status != c.status || !strings.Contains(body, c.want) {
			t.Errorf("%s %s: %d %s", c.method, c.path, status, body)
		}
	}
}

func TestAPIKeyListShowsAMemberOnlyTheirOwn(t *testing.T) {
	agent := uuid.NewString()
	st := &rows{keys: []domain.APIKey{
		{ID: uuid.NewString(), Name: "mine", CreatedBy: "me", TokenPrefix: "aat_1", IsActive: true, AgentID: &agent, CreatedAt: time.Date(2026, 1, 2, 3, 4, 5, 600000000, time.UTC)},
		{ID: uuid.NewString(), Name: "theirs", CreatedBy: "them"},
	}}
	status, body := jsonDo(t, rest(t, authn.KindSession, false, service.Deps{Store: st}), "GET", "/v1/workspaces/acme/api-keys/", "")
	want := `[{"id":"` + st.keys[0].ID + `","name":"mine","token_prefix":"aat_1","is_active":true,"expires_at":null,"access_count":0,"last_accessed_at":null,"created_at":"2026-01-02T03:04:05.600000Z","agent_id":"` + agent + `"}]`
	if status != 200 || body != want {
		t.Fatalf("%d %s", status, body)
	}
	if _, body := jsonDo(t, rest(t, authn.KindSession, true, service.Deps{Store: st}), "GET", "/v1/workspaces/acme/api-keys/", ""); strings.Count(body, `"id"`) != 2 {
		t.Fatalf("admin %s", body)
	}
}

func TestExternalIdentities(t *testing.T) {
	id := uuid.NewString()
	alice := "alice"
	st := &rows{links: []domain.ExternalIdentity{
		{ID: id, Provider: "telegram", ExternalID: "42", CreatedAt: time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)},
		{ID: id, Provider: "telegram", ExternalID: "43", Username: &alice, CreatedAt: time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)},
	}}
	s := rest(t, authn.KindSession, true, service.Deps{Store: st, LinkCodes: codes{}})
	status, body := jsonDo(t, s, "GET", "/v1/me/external-identities", "")
	if status != 200 || body != `[{"id":"`+id+`","provider":"telegram","external_id":"42","linked_at":"2026-01-02T03:04:05","username":null,"display_name":null},`+
		`{"id":"`+id+`","provider":"telegram","external_id":"43","linked_at":"2026-01-02T03:04:05","username":"alice","display_name":null}]` {
		t.Fatalf("%d %s", status, body)
	}
	status, body = jsonDo(t, s, "POST", "/v1/me/external-identities/telegram/link", `{"bot":"agentarea_bot"}`)
	if status != 200 || body != `{"url":"https://t.me/agentarea_bot?start=link_CODE","expires_in":600}` {
		t.Fatalf("%d %s", status, body)
	}
}

func TestATelegramLinkOfferIsAcceptedOnceByAMemberOfTheBotsWorkspace(t *testing.T) {
	account := func(id, ws string) domain.LinkOffer {
		return domain.LinkOffer{MessengerAccount: domain.MessengerAccount{Provider: "telegram", ExternalID: id, Username: "alice", Name: "Alice Liddell"},
			WorkspaceID: ws, SourceID: "src", Bot: "door_bot"}
	}
	st := &rows{holders: map[string]string{"7": "someone-else"}, owners: map[string]string{"mine": "me", "team": "boss", "strangers": "boss"}}
	offers := map[string]domain.LinkOffer{"A": account("42", "mine"), "TAKEN": account("7", "mine"),
		"TEAM": account("8", "team"), "FOREIGN": account("9", "strangers"), "GONE_WS": account("10", "deleted")}
	d := service.Deps{Store: st, LinkCodes: codes{offers: offers}, Reader: members{"team:me": true}}
	s := rest(t, authn.KindSession, true, d)
	key := rest(t, authn.KindAPIKey, true, d)

	for _, c := range []struct {
		s            *httptest.Server
		path, body   string
		status       int
		want         string
		exactlyEqual bool
	}{
		{key, "preview", `{"code":"A"}`, 403, "This credential cannot link a messenger account", false},
		{s, "preview", `{}`, 422, `"loc":["body","code"]`, false},
		{s, "preview", `{"code":"NOPE"}`, 404, "This link has expired or was already used", false},
		{s, "preview", `{"code":"A"}`, 200, `{"provider":"telegram","external_id":"42","username":"alice","display_name":"Alice Liddell","bot":"door_bot","workspace_name":"Acme mine","linked_to":null}`, true},
		{s, "preview", `{"code":"TAKEN"}`, 200, `"linked_to":"another_account"`, false},
		{s, "preview", `{"code":"TEAM"}`, 200, `"workspace_name":"Acme team"`, false},
		{s, "preview", `{"code":"FOREIGN"}`, 403, "Only a member of the bot's workspace", false},
		{s, "accept", `{"code":"FOREIGN"}`, 403, "Only a member of the bot's workspace", false},
		{s, "preview", `{"code":"GONE_WS"}`, 404, "This link has expired or was already used", false},
		{s, "accept", `{"code":"TAKEN"}`, 409, "already linked to another AgentArea account", false},
		{s, "accept", `{"code":"A"}`, 200, `"external_id":"42","linked_at":"`, false},
		{s, "accept", `{"code":"A"}`, 404, "This link has expired or was already used", false},
		{s, "accept", `{"code":"TEAM"}`, 200, `"external_id":"8"`, false},
	} {
		status, body := jsonDo(t, c.s, "POST", "/v1/me/external-identities/telegram/offer/"+c.path, c.body)
		if status != c.status || (c.exactlyEqual && body != c.want) || !strings.Contains(body, c.want) {
			t.Errorf("%s %s: %d %s", c.path, c.body, status, body)
		}
	}
	if st.holders["42"] != "me" || st.holders["7"] != "someone-else" || st.holders["9"] != "" {
		t.Fatalf("holders %v", st.holders)
	}
	if _, ok := offers["FOREIGN"]; !ok {
		t.Fatal("a refused stranger spent the code")
	}
}

func multipartBody(t *testing.T, field string, file bool) (string, io.Reader) {
	t.Helper()
	var b bytes.Buffer
	w := multipart.NewWriter(&b)
	if file {
		fw, err := w.CreateFormFile(field, "logo.gif")
		if err != nil {
			t.Fatal(err)
		}
		_, _ = fw.Write([]byte("GIF89a"))
	} else if err := w.WriteField(field, "text"); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	return w.FormDataContentType(), &b
}

func TestLogoUpload(t *testing.T) {
	s := rest(t, authn.KindSession, true, service.Deps{Logos: noLogos{}})
	ct, b := multipartBody(t, "other", true)
	if status, body := do(t, s, "PUT", "/v1/workspaces/acme/logo", ct, b); status != 422 || !strings.Contains(body, `"type":"missing","loc":["body","file"]`) {
		t.Fatalf("no file: %d %s", status, body)
	}
	ct, b = multipartBody(t, "file", false)
	if status, body := do(t, s, "PUT", "/v1/workspaces/acme/logo", ct, b); status != 422 || !strings.Contains(body, "Expected UploadFile") {
		t.Fatalf("text field: %d %s", status, body)
	}
	ct, b = multipartBody(t, "file", true)
	if status, body := do(t, s, "PUT", "/v1/workspaces/acme/logo", ct, b); status != 422 || !strings.Contains(body, "Logo must be a PNG, JPEG or WebP image") {
		t.Fatalf("gif: %d %s", status, body)
	}
	member := rest(t, authn.KindSession, false, service.Deps{Logos: noLogos{}})
	if status, _ := do(t, member, "PUT", "/v1/workspaces/acme/logo", "", nil); status != 403 {
		t.Fatalf("member: %d", status)
	}
}
