package app

import (
	"context"
	"net/http"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster/secrets"
)

func TestDelegateSecretsFindAWorkspaceSecretByName(t *testing.T) {
	ctx := context.Background()
	d := pulseDB(t)
	f, err := secrets.NewFactory(ksecrets.Config{Backend: ksecrets.BackendDatabase, EncryptionKey: "48pCGWLB98XVpxnYbIedmj9j43n2SXLAu8oCQePXx1g="}, http.DefaultClient)
	if err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	if err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		for _, name := range []string{"aadocs-key", "oauth-token"} {
			if err := f.Manager(s, "u1").Set(ctx, name, "tok"); err != nil {
				return err
			}
		}
		_, err := s.Q().Exec(ctx, `UPDATE encrypted_secrets SET owner_type = 'mcp_instance' WHERE secret_name = 'oauth-token'`)
		return err
	}); err != nil {
		t.Fatal(err)
	}
	found := delegateSecrets{d: coreDeps{DB: d, Graph: &wiringGraph{objects: map[string]bool{}}, Secrets: f}}
	if s, ok, err := found.SecretNamed(ctx, ws, "aadocs-key"); err != nil || !ok || s.OwnerType != nil {
		t.Fatalf("a user's secret = %+v %v %v", s, ok, err)
	}
	if s, ok, err := found.SecretNamed(ctx, ws, "oauth-token"); err != nil || !ok || s.OwnerType == nil || *s.OwnerType != "mcp_instance" {
		t.Fatalf("a managed secret = %+v %v %v", s, ok, err)
	}
	if _, ok, err := found.SecretNamed(ctx, ws, "missing"); err != nil || ok {
		t.Fatalf("a missing secret = %v %v", ok, err)
	}
}
