package app

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/operator"
	catalogservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
	catalogstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/store"
	connectionsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
	governanceservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/service"
	modelsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/service"
	modelsstore "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/secrets"
)

type operatorSecrets map[string]string

func (s operatorSecrets) Read(_ context.Context, namespace, name, key string) (string, error) {
	if v, ok := s[namespace+"/"+name+"/"+key]; ok {
		return v, nil
	}
	return "", errors.New("not found")
}

func TestTheOperatorWritesEachDeclarationOnceThroughItsOwners(t *testing.T) {
	d := pulseDB(t)
	ctx := context.Background()
	if err := d.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		_, err := q.Exec(ctx, `INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ('platform', 'Platform', 'platform', 'platform')
			ON CONFLICT DO NOTHING`)
		if err != nil {
			return err
		}
		_, err = q.Exec(ctx, `INSERT INTO provider_specs (id, provider_key, name, provider_type, is_builtin, workspace_id, created_by, created_at, updated_at)
			VALUES (gen_random_uuid(), 'openrouter', 'OpenRouter', 'openrouter', true, 'platform', 'platform', now(), now())`)
		return err
	}); err != nil {
		t.Fatal(err)
	}
	factory, err := secrets.NewFactory(ksecrets.Config{Backend: ksecrets.BackendDatabase, EncryptionKey: "48pCGWLB98XVpxnYbIedmj9j43n2SXLAu8oCQePXx1g="}, http.DefaultClient)
	if err != nil {
		t.Fatal(err)
	}
	session := secrets.NewSession(factory)
	models := modelsservice.New(modelsservice.Deps{DB: d, Store: modelsstore.Store{}, Secrets: session})
	connections := connectionsservice.New(connectionsservice.Deps{DB: d, Secrets: session})
	r := operator.New(operator.Deps{
		Catalog: catalogservice.New(catalogservice.Deps{DB: d, Specs: catalogstore.Specs{}}).Platform(), Models: models,
		Connections: connections, Egress: governanceservice.New(governanceservice.Deps{DB: d}),
		Secrets: operatorSecrets{"agentarea/keys/api": "sk-1", "agentarea/keys/token": "tok"}, Log: slog.New(slog.DiscardHandler),
	})
	provider := map[string]any{"providerKey": "openrouter", "name": "OpenRouter", "apiKeySecretRef": map[string]any{"name": "keys", "key": "api"},
		"models": []any{map[string]any{"modelName": "z-ai/glm-4.6", "inputCostPerToken": 0.0000004, "outputCostPerToken": 0.0000016,
			"reasoningEfforts": []any{"low", "high"}, "tags": []any{"default"}}}}
	connection := map[string]any{"transport": "mcp", "name": "Search", "endpointUrl": "https://mcp.example/", "tokenSecretRef": map[string]any{"name": "keys", "key": "token"}}
	exit := map[string]any{"name": "eu", "via": "proxy-eu"}
	for range 2 {
		if out := r.Provider(ctx, "agentarea", "or", provider); out.Status["phase"] != "Synced" {
			t.Fatalf("provider %+v", out)
		}
		if out := r.Connection(ctx, "agentarea", "c", connection); out.Status["phase"] != "Synced" {
			t.Fatalf("connection %+v", out)
		}
		if out := r.EgressExit(ctx, "agentarea", "e", exit); out.Status["phase"] != "Synced" {
			t.Fatalf("exit %+v", out)
		}
	}
	for query, want := range map[string]int{
		`SELECT count(*) FROM provider_configs WHERE id = '2178e2fa-d5c3-5731-b4bc-655efd4d86f5' AND managed_by = 'platform'
			AND api_key = 'provider_config_2178e2fa-d5c3-5731-b4bc-655efd4d86f5' AND api_key_secret_id IS NOT NULL`: 1,
		`SELECT count(*) FROM model_specs WHERE model_name = 'z-ai/glm-4.6' AND workspace_id = 'platform'
			AND input_cost_per_token = 0.0000004 AND reasoning_efforts = '["low", "high"]'::jsonb`: 1,
		`SELECT count(*) FROM model_instances WHERE id = 'd7b86a81-95f9-5c2d-8cea-9af6eaa6e62c' AND tags = '["default"]'::jsonb`:       1,
		`SELECT count(*) FROM encrypted_secrets WHERE workspace_id = 'platform' AND owner_type IN ('provider_config', 'mcp_instance')`: 2,
		`SELECT count(*) FROM mcp_servers WHERE workspace_id = 'platform' AND slug = 'search' AND remote_url = 'https://mcp.example/'`: 1,
		`SELECT count(*) FROM mcp_server_instances WHERE id = '0b7c1e62-ed22-5cbf-8488-31e93f055566' AND managed_by = 'platform'`:      1,
		`SELECT count(*) FROM egress_exits WHERE managed_by = 'platform' AND via = 'proxy-eu'`:                                         1,
	} {
		var n int
		if err := d.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			return q.QueryRow(ctx, query).Scan(&n)
		}); err != nil || n != want {
			t.Errorf("%d rows (want %d), %v: %s", n, want, err, query)
		}
	}
	if defaults, err := models.PlatformDefaults(ctx); err != nil || len(defaults) != 1 || defaults[0] != "z-ai/glm-4.6" {
		t.Fatalf("defaults %v %v", defaults, err)
	}
}
