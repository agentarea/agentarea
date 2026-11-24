package handlers

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/service"
)

type memory struct {
	wallets  map[uuid.UUID]api.Wallet
	payments []api.Payment
	secrets  map[string]string
}

type fakeDB struct {
	db.Database
}

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type fakeSecrets struct{ m *memory }

func (f fakeSecrets) Manager(db.Session, string) secrets.Manager { return fakeManager(f) }

type fakeManager struct{ m *memory }

func (f fakeManager) Get(_ context.Context, n string) (string, error) {
	v, ok := f.m.secrets[n]
	if !ok {
		return "", secrets.ErrNotFound
	}
	return v, nil
}
func (f fakeManager) Set(_ context.Context, n, v string) error { f.m.secrets[n] = v; return nil }
func (f fakeManager) Delete(_ context.Context, n string) (bool, error) {
	_, ok := f.m.secrets[n]
	delete(f.m.secrets, n)
	return ok, nil
}
func (f fakeManager) Has(_ context.Context, n string) (bool, error) {
	_, ok := f.m.secrets[n]
	return ok, nil
}
func (fakeManager) ExternalRef(string) (string, bool) { return "", false }

type fakeStore struct {
	service.Store
	m *memory
}

var stamp = time.Date(2026, 11, 12, 1, 2, 3, 123456000, time.UTC)

func (f fakeStore) WalletByAgent(_ context.Context, _ db.Session, agent uuid.UUID) (api.Wallet, bool, error) {
	for _, w := range f.m.wallets {
		if w.AgentID == agent.String() {
			return w, true, nil
		}
	}
	return api.Wallet{}, false, nil
}

func (f fakeStore) CreateWallet(_ context.Context, _ db.Session, id, agent uuid.UUID, by string, n domain.New, now time.Time) (api.Wallet, error) {
	w := api.Wallet{
		ID: id.String(), AgentID: agent.String(), CreatedBy: by, Type: n.Type, X402Config: n.X402Config, MPPConfig: n.MPPConfig,
		Budget: money.MustParse(n.Budget), Period: n.Period, Status: api.StatusActive, CreatedAt: now, UpdatedAt: now,
	}
	if n.CredentialsRef != nil {
		r := secrets.Ref(*n.CredentialsRef)
		w.CredentialsRef = &r
	}
	f.m.wallets[id] = w
	return w, nil
}

func (f fakeStore) UpdateWallet(_ context.Context, _ db.Session, id uuid.UUID, p domain.Patch, now time.Time) (api.Wallet, bool, error) {
	w := f.m.wallets[id]
	if p.Budget != nil {
		w.Budget = money.MustParse(*p.Budget)
	}
	if p.Status != nil {
		w.Status = *p.Status
	}
	if p.Type != nil {
		w.Type = *p.Type
	}
	if p.MPPConfig != nil {
		w.MPPConfig = p.MPPConfig
	}
	if p.CredentialsRef != nil {
		r := secrets.Ref(*p.CredentialsRef)
		w.CredentialsRef = &r
	}
	w.UpdatedAt = now
	f.m.wallets[id] = w
	return w, true, nil
}

func (f fakeStore) DeleteWallet(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	delete(f.m.wallets, id)
	return true, nil
}

func (f fakeStore) SumSince(context.Context, db.Session, string, *time.Time, *time.Time) (money.Decimal, error) {
	return money.MustParse("1.250000"), nil
}

func match(f domain.PaymentFilter, p api.Payment) bool {
	return (f.Protocol == nil || *f.Protocol == p.Protocol) && (f.Status == nil || *f.Status == p.Status)
}

func (f fakeStore) ListPayments(_ context.Context, _ db.Session, _ string, fl domain.PaymentFilter, limit, offset int32) ([]api.Payment, error) {
	var out []api.Payment
	for _, p := range f.m.payments {
		if match(fl, p) {
			out = append(out, p)
		}
	}
	if int(offset) >= len(out) {
		return nil, nil
	}
	out = out[offset:]
	if int(limit) < len(out) {
		out = out[:limit]
	}
	return out, nil
}

func (f fakeStore) CountPayments(_ context.Context, _ db.Session, _ string, fl domain.PaymentFilter) (int, error) {
	n := 0
	for _, p := range f.m.payments {
		if match(fl, p) {
			n++
		}
	}
	return n, nil
}

type fakeAgents struct{ known map[string]uuid.UUID }

func (f fakeAgents) Resolve(_ context.Context, _ scope.Workspace, s string) (uuid.UUID, bool, error) {
	id, ok := f.known[strings.ToLower(s)]
	return id, ok, nil
}

type rig struct {
	*httptest.Server
	m     *memory
	agent uuid.UUID
	admin *bool
}

func newRig(t *testing.T) rig {
	t.Helper()
	m := &memory{wallets: map[uuid.UUID]api.Wallet{}, secrets: map[string]string{}}
	agent := uuid.New()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), caller)))
		})
	}
	isAdmin := true
	admin := func(context.Context) error {
		if !isAdmin {
			return httpx.Forbidden("Only a workspace admin may perform this action")
		}
		return nil
	}
	svc := service.New(service.Deps{
		DB: fakeDB{}, Store: fakeStore{m: m}, Secrets: fakeSecrets{m},
		Agents: fakeAgents{known: map[string]uuid.UUID{agent.String(): agent, "my-agent": agent}},
		Log:    slog.New(slog.DiscardHandler), Now: func() time.Time { return stamp },
	})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, New(svc, admin))
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return rig{Server: s, m: m, agent: agent, admin: &isAdmin}
}

func (r rig) call(t *testing.T, method, agent, path, body string) (int, string) {
	t.Helper()
	req, err := http.NewRequest(method, r.URL+"/v1/workspaces/acme/agents/"+agent+"/wallet"+path, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(raw)
}

const createDual = `{"wallet_type":"dual","x402_config":{},"mpp_config":{"session_budget_usd":0.1},` +
	`"credentials":{"x402_private_key":"0xSECRETKEY"},"service_budget_usd":5,"service_budget_period":"daily"}`

func TestCreateRendersInPythonOrderAndNeverReturnsKeys(t *testing.T) {
	r := newRig(t)
	status, body := r.call(t, http.MethodPost, r.agent.String(), "", createDual)
	if status != http.StatusCreated {
		t.Fatalf("%d %s", status, body)
	}
	var w map[string]any
	if err := json.Unmarshal([]byte(body), &w); err != nil {
		t.Fatal(err)
	}
	want := `{"id":"` + w["id"].(string) + `","agent_id":"` + r.agent.String() + `","wallet_type":"dual",` +
		`"x402_config":{"network":"eip155:8453","facilitator_url":"https://x402.org/facilitator","scheme":"exact","signer_type":"evm"},` +
		`"mpp_config":{"payment_method_types":["charge"],"session_budget_usd":"0.1","stripe_profile_id":null,"chain_id":null,"rpc_url":null,"currency":null,"recipient":null,"decimals":6},` +
		`"has_credentials":true,"service_budget_usd":"5.000000","service_budget_period":"daily","status":"active",` +
		`"created_at":"2026-11-12T01:02:03.123456Z","updated_at":"2026-11-12T01:02:03.123456Z"}`
	if body != want {
		t.Fatalf("body\n%s\nwant\n%s", body, want)
	}
	if strings.Contains(body, "SECRETKEY") {
		t.Fatal("a key came back in the response")
	}
	if got := r.m.secrets["wallet_creds_"+r.agent.String()]; got != `{"x402_private_key": "0xSECRETKEY"}` {
		t.Fatalf("stored secret %q", got)
	}

	status, got := r.call(t, http.MethodGet, strings.ToUpper(r.agent.String()), "", "")
	if status != http.StatusOK || got != body {
		t.Fatalf("read back by uuid %d %s", status, got)
	}
	if status, got = r.call(t, http.MethodGet, "my-agent", "", ""); status != http.StatusOK || got != body {
		t.Fatalf("read back by slug %d %s", status, got)
	}
}

func TestErrorsAreProblemDetails(t *testing.T) {
	r := newRig(t)
	for _, c := range []struct {
		method, agent, path, body string
		status                    int
		detail                    string
	}{
		{http.MethodGet, r.agent.String(), "", "", 404, "No wallet configured for this agent"},
		{http.MethodGet, uuid.NewString(), "", "", 404, "Agent not found"},
		{http.MethodGet, "nobody", "/balance", "", 404, "Agent not found"},
		{http.MethodPut, r.agent.String(), "", `{}`, 404, "No wallet configured for this agent"},
		{http.MethodDelete, r.agent.String(), "", "", 404, "No wallet configured for this agent"},
		{http.MethodPost, r.agent.String(), "/fund", `{"service_budget_usd":1}`, 404, "No wallet configured for this agent"},
		{http.MethodPost, r.agent.String(), "", `{"wallet_type":"dual","x402_config":{}}`, 400, "mpp_config is required for wallet_type 'dual'"},
		{http.MethodPost, r.agent.String(), "", `{"wallet_type":"x402"}`, 400, "x402_config is required for wallet_type 'x402'"},
	} {
		status, body := r.call(t, c.method, c.agent, c.path, c.body)
		if status != c.status || !strings.Contains(body, `"detail":"`+c.detail+`"`) {
			t.Errorf("%s %s%s: %d %s", c.method, c.agent, c.path, status, body)
		}
	}
	if status, body := r.call(t, http.MethodPost, r.agent.String(), "", `{"wallet_type":"x402","x402_config":{}}`); status != 201 {
		t.Fatalf("%d %s", status, body)
	}
	status, body := r.call(t, http.MethodPost, r.agent.String(), "", `{"wallet_type":"x402","x402_config":{}}`)
	if status != http.StatusConflict || !strings.Contains(body, `"detail":"Wallet already exists for this agent"`) {
		t.Fatalf("duplicate: %d %s", status, body)
	}
}

func TestValidation422(t *testing.T) {
	r := newRig(t)
	for name, c := range map[string]struct{ body, want string }{
		"no body":               {``, `"type":"missing"`},
		"not an object":         {`[]`, `"type":"model_attributes_type"`},
		"no type":               {`{}`, `"loc":["body","wallet_type"]`},
		"bad type":              {`{"wallet_type":"btc"}`, `"msg":"Input should be 'x402', 'mpp' or 'dual'"`},
		"bad period":            {`{"wallet_type":"x402","service_budget_period":"weekly"}`, `"msg":"Input should be 'execution', 'daily' or 'monthly'"`},
		"null period":           {`{"wallet_type":"x402","service_budget_period":null}`, `"type":"enum"`},
		"negative budget":       {`{"wallet_type":"x402","service_budget_usd":-1}`, `"msg":"Input should be greater than or equal to 0"`},
		"budget at ceiling":     {`{"wallet_type":"x402","service_budget_usd":"1000000000000"}`, `"msg":"Input should be less than 1000000000000"`},
		"huge exponent":         {`{"wallet_type":"x402","service_budget_usd":"1e2000000000"}`, `"type":"less_than"`},
		"rounds to the ceiling": {`{"wallet_type":"x402","service_budget_usd":"999999999999.9999995"}`, `service_budget_usd must be less than 1000000000000`},
		"not money":             {`{"wallet_type":"x402","service_budget_usd":"abc"}`, `'abc' is not a money amount`},
		"null budget":           {`{"wallet_type":"x402","service_budget_usd":null}`, `None is not a money amount`},
		"bool budget":           {`{"wallet_type":"x402","service_budget_usd":true}`, `True is not a money amount`},
		"mpp without session":   {`{"wallet_type":"mpp","mpp_config":{}}`, `"loc":["body","mpp_config","session_budget_usd"]`},
		"mpp negative session":  {`{"wallet_type":"mpp","mpp_config":{"session_budget_usd":-1}}`, `"loc":["body","mpp_config","session_budget_usd"]`},
		"x402 field type":       {`{"wallet_type":"x402","x402_config":{"network":5}}`, `"loc":["body","x402_config","network"]`},
		"x402 not an object":    {`{"wallet_type":"x402","x402_config":"x"}`, `"type":"model_attributes_type"`},
		"credential type":       {`{"wallet_type":"x402","credentials":{"x402_private_key":1}}`, `"loc":["body","credentials","x402_private_key"]`},
		"chain id":              {`{"wallet_type":"mpp","mpp_config":{"session_budget_usd":1,"chain_id":"x"}}`, `"type":"int_parsing"`},
	} {
		status, body := r.call(t, http.MethodPost, r.agent.String(), "", c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s: %d %s", name, status, body)
		}
	}
	if len(r.m.wallets) != 0 || len(r.m.secrets) != 0 {
		t.Fatal("a refused request wrote something")
	}
	for _, c := range []struct{ path, want string }{
		{"/payments?page=0", `"loc":["query","page"]`},
		{"/payments?page_size=201", `"type":"less_than_equal"`},
		{"/payments?page_size=x", `"type":"int_parsing"`},
		{"/payments?from_date=yesterday", `"loc":["query","from_date"]`},
		{"/payments?to_date=2026-13-01", `"loc":["query","to_date"]`},
	} {
		status, body := r.call(t, http.MethodGet, r.agent.String(), c.path, "")
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s: %d %s", c.path, status, body)
		}
	}
}

func TestOrderOfRefusals(t *testing.T) {
	r := newRig(t)
	*r.admin = false
	const forbidden = `Only a workspace admin may perform this action`
	for _, c := range []struct {
		name, method, agent, path, body string
		status                          int
		want                            string
	}{
		{"read of a missing agent: 403 first", http.MethodGet, uuid.NewString(), "", "", 403, forbidden},
		{"read of a bad query: 403 first", http.MethodGet, r.agent.String(), "/payments?page=0", "", 403, forbidden},
		{"mutation of a missing agent: 404 first", http.MethodPost, uuid.NewString(), "", `{"wallet_type":"x402","x402_config":{}}`, 404, "Agent not found"},
		{"mutation with a bad body: 422 first", http.MethodPut, r.agent.String(), "", `{"status":"zombie"}`, 422, `"type":"enum"`},
		{"create", http.MethodPost, r.agent.String(), "", `{"wallet_type":"x402","x402_config":{}}`, 403, forbidden},
		{"update", http.MethodPut, r.agent.String(), "", `{}`, 403, forbidden},
		{"fund", http.MethodPost, r.agent.String(), "/fund", `{"service_budget_usd":1}`, 403, forbidden},
		{"delete", http.MethodDelete, r.agent.String(), "", "", 403, forbidden},
		{"balance", http.MethodGet, r.agent.String(), "/balance", "", 403, forbidden},
		{"payments", http.MethodGet, r.agent.String(), "/payments", "", 403, forbidden},
	} {
		status, body := r.call(t, c.method, c.agent, c.path, c.body)
		if status != c.status || !strings.Contains(body, c.want) {
			t.Errorf("%s: %d %s", c.name, status, body)
		}
	}
	if len(r.m.wallets) != 0 {
		t.Fatal("a non-admin created a wallet")
	}
}

func TestUpdateFundBalanceDelete(t *testing.T) {
	r := newRig(t)
	if status, body := r.call(t, http.MethodPost, r.agent.String(), "", createDual); status != 201 {
		t.Fatalf("%d %s", status, body)
	}
	status, body := r.call(t, http.MethodPut, r.agent.String(), "", `{"status":"disabled","wallet_type":null,"service_budget_usd":"7.5","credentials":{"mpp_tempo_key":"tk"}}`)
	if status != 200 || !strings.Contains(body, `"status":"disabled"`) || !strings.Contains(body, `"service_budget_usd":"7.500000"`) || !strings.Contains(body, `"wallet_type":"dual"`) {
		t.Fatalf("update %d %s", status, body)
	}
	if got := r.m.secrets["wallet_creds_"+r.agent.String()]; got != `{"x402_private_key": "0xSECRETKEY", "mpp_tempo_key": "tk"}` {
		t.Fatalf("keys after a one-key update: %q", got)
	}
	status, body = r.call(t, http.MethodPost, r.agent.String(), "/fund", `{"service_budget_usd":0.1234565}`)
	if status != 200 || !strings.Contains(body, `"service_budget_usd":"0.123457"`) {
		t.Fatalf("fund rounds half up to six places: %d %s", status, body)
	}
	status, body = r.call(t, http.MethodGet, r.agent.String(), "/balance", "")
	if status != 200 || body != `{"service_budget_usd":"0.123457","service_budget_period":"daily","total_spent_current_period":"1.250000","remaining":"0"}` {
		t.Fatalf("balance %d %s", status, body)
	}
	status, body = r.call(t, http.MethodDelete, r.agent.String(), "", "")
	if status != 204 || body != "" || len(r.m.wallets) != 0 || len(r.m.secrets) != 0 {
		t.Fatalf("delete %d %q wallets %d secrets %d", status, body, len(r.m.wallets), len(r.m.secrets))
	}
}

func TestPaymentsPageAndFilters(t *testing.T) {
	r := newRig(t)
	status, body := r.call(t, http.MethodGet, r.agent.String(), "/payments", "")
	if status != 200 || body != `{"items":[],"total":0,"page":1,"page_size":50}` {
		t.Fatalf("empty history of an agent without a wallet: %d %s", status, body)
	}
	tx := "0xtx"
	for i, proto := range []string{"x402", "mpp", "x402"} {
		r.m.payments = append(r.m.payments, api.Payment{
			ID: uuid.NewString(), AgentID: r.agent.String(), ExecutionID: "e", Protocol: proto, Amount: money.MustParse("0.500000"),
			Recipient: "0xr", TxHash: &tx, ToolName: "t", ToolCallID: "c", Status: map[bool]string{true: "completed", false: "failed"}[i != 1],
			ProtocolMetadata: json.RawMessage(`{"network": "eip155:8453"}`), CreatedAt: stamp,
		})
	}
	status, body = r.call(t, http.MethodGet, r.agent.String(), "/payments?protocol=x402&page_size=1&page=2", "")
	var page struct {
		Items []map[string]any `json:"items"`
		Total int              `json:"total"`
		Page  int              `json:"page"`
		Size  int              `json:"page_size"`
	}
	if err := json.Unmarshal([]byte(body), &page); err != nil || status != 200 {
		t.Fatalf("%d %s %v", status, body, err)
	}
	if page.Total != 2 || page.Page != 2 || page.Size != 1 || len(page.Items) != 1 {
		t.Fatalf("page %+v", page)
	}
	item := page.Items[0]
	if item["amount_usd"] != "0.500000" || item["tx_hash"] != "0xtx" || item["error_message"] != nil || item["created_at"] != "2026-11-12T01:02:03.123456Z" {
		t.Fatalf("item %v", item)
	}
	if _, has := item["idempotency_key"]; has {
		t.Fatal("idempotency_key is not part of the response")
	}
	if _, has := item["wallet_id"]; has {
		t.Fatal("wallet_id is not part of the response")
	}
}

func TestUTCISOMatchesPythonIsoformat(t *testing.T) {
	for in, want := range map[time.Time]string{
		time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC):         "2026-01-02T03:04:05Z",
		time.Date(2026, 1, 2, 3, 4, 5, 120000000, time.UTC): "2026-01-02T03:04:05.120000Z",
		time.Date(2026, 1, 2, 3, 4, 5, 1000, time.UTC):      "2026-01-02T03:04:05.000001Z",
	} {
		if got := utcISO(in); got != want {
			t.Errorf("%v: %s, want %s", in, got, want)
		}
	}
}
