package secrets

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"io"
	"log/slog"
	"os"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// The resolver reads secrets with raw SQL against the schema alembic produces,
// and the rule it has to enforce — a container only ever receives secrets from
// its own instance's workspace — lives entirely in that SQL. A stubbed database
// would answer whatever the test author wired up and would pass while the real
// query read across tenants, which is exactly the bug these tests exist to keep
// out. So the schema comes from the migrations. See repository_db_test.go in
// internal/mcpgateway for the same arrangement and the local setup recipe.

const (
	resolverTestDSNEnv  = "MCP_GATEWAY_TEST_DATABASE_URL"
	resolverRequireDBEn = "MCP_GATEWAY_REQUIRE_DB"
)

func resolverTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv(resolverTestDSNEnv)
	if dsn == "" {
		if os.Getenv(resolverRequireDBEn) != "" {
			t.Fatalf("%s is set but %s is empty: the schema-backed secret resolver tests were meant to run here, not skip",
				resolverRequireDBEn, resolverTestDSNEnv)
		}
		t.Skipf("%s not set; skipping schema-backed secret resolver tests", resolverTestDSNEnv)
	}

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open test database: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		t.Fatalf("ping test database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

// fernetEncrypt mirrors the token layout fernetDecrypt parses, so a test can
// plant a secret the production decryption path accepts.
func fernetEncrypt(t *testing.T, key []byte, plaintext string) string {
	t.Helper()

	iv := make([]byte, aes.BlockSize)
	if _, err := io.ReadFull(rand.Reader, iv); err != nil {
		t.Fatalf("generate iv: %v", err)
	}

	padding := aes.BlockSize - len(plaintext)%aes.BlockSize
	padded := append([]byte(plaintext), make([]byte, padding)...)
	for i := len(plaintext); i < len(padded); i++ {
		padded[i] = byte(padding)
	}

	block, err := aes.NewCipher(key[16:])
	if err != nil {
		t.Fatalf("new cipher: %v", err)
	}
	ciphertext := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(ciphertext, padded)

	token := make([]byte, 0, 1+8+len(iv)+len(ciphertext)+sha256.Size)
	token = append(token, 0x80)
	timestamp := make([]byte, 8)
	binary.BigEndian.PutUint64(timestamp, uint64(time.Now().Unix()))
	token = append(token, timestamp...)
	token = append(token, iv...)
	token = append(token, ciphertext...)

	mac := hmac.New(sha256.New, key[:16])
	mac.Write(token)
	token = append(token, mac.Sum(nil)...)

	return base64.URLEncoding.EncodeToString(token)
}

func newSchemaBackedResolver(t *testing.T, db *sql.DB) (*DatabaseSecretResolver, []byte) {
	t.Helper()
	key := make([]byte, 32)
	if _, err := io.ReadFull(rand.Reader, key); err != nil {
		t.Fatalf("generate fernet key: %v", err)
	}
	return &DatabaseSecretResolver{
		db:     db,
		logger: slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelDebug})),
		key:    key,
	}, key
}

func insertInstance(t *testing.T, db *sql.DB, instanceID, workspaceID string) {
	t.Helper()
	_, err := db.Exec(`
		INSERT INTO mcp_server_instances
			(id, name, server_spec_id, json_spec, verification, network_scope,
			 workspace_id, created_by, created_at, updated_at)
		VALUES ($1::uuid, $2, 'spec-under-test', '{}'::json, '{}'::json, 'private',
			 $3, 'resolver-test', now(), now())`,
		instanceID, "instance-"+instanceID[:8], workspaceID)
	if err != nil {
		t.Fatalf("insert instance %s: %v", instanceID, err)
	}
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM mcp_server_instances WHERE id = $1::uuid`, instanceID)
	})
}

func insertSecret(t *testing.T, db *sql.DB, workspaceID, name, encrypted string) {
	t.Helper()
	_, err := db.Exec(`
		INSERT INTO encrypted_secrets
			(id, workspace_id, secret_name, encrypted_value, created_by, created_at, updated_at)
		VALUES (gen_random_uuid(), $1, $2, $3, 'resolver-test', now(), now())`,
		workspaceID, name, encrypted)
	if err != nil {
		t.Fatalf("insert secret %s in %s: %v", name, workspaceID, err)
	}
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM encrypted_secrets WHERE workspace_id = $1 AND secret_name = $2`,
			workspaceID, name)
	})
}

// A secret named after another workspace's instance must stay invisible to it.
// Secret names are globally unique only by accident today (they embed a UUID);
// once a workspace can name a secret, planting `mcp_instance_<their-uuid>_VAR`
// is how one tenant would inject environment into another tenant's container.
func TestResolveInstanceEnvVarsRefusesForeignWorkspaceSecret(t *testing.T) {
	db := resolverTestDB(t)
	resolver, key := newSchemaBackedResolver(t, db)

	const (
		victimInstance = "11111111-1111-4111-8111-111111111111"
		victimWS       = "resolver-test-ws-victim"
		attackerWS     = "resolver-test-ws-attacker"
	)
	secretName := fmt.Sprintf("mcp_instance_%s_API_KEY", victimInstance)

	insertInstance(t, db, victimInstance, victimWS)
	insertSecret(t, db, attackerWS, secretName, fernetEncrypt(t, key, "attacker-controlled"))

	_, err := resolver.ResolveInstanceEnvVars(victimInstance, []string{"API_KEY"})
	if err == nil {
		t.Fatal("ResolveInstanceEnvVars() error = nil, want a failure: the only matching secret belongs to another workspace")
	}
}

// With the same name present in both workspaces, the instance's own workspace
// decides. The pre-fix query had no workspace predicate and no ORDER BY, so it
// returned whichever row the scan reached first.
func TestResolveInstanceEnvVarsPrefersOwnWorkspaceOverSameNamedForeignSecret(t *testing.T) {
	db := resolverTestDB(t)
	resolver, key := newSchemaBackedResolver(t, db)

	const (
		victimInstance = "22222222-2222-4222-8222-222222222222"
		victimWS       = "resolver-test-ws-owner"
		attackerWS     = "resolver-test-ws-squatter"
	)
	secretName := fmt.Sprintf("mcp_instance_%s_API_KEY", victimInstance)

	insertInstance(t, db, victimInstance, victimWS)
	// Planted first so a scan without a workspace predicate reaches it first.
	insertSecret(t, db, attackerWS, secretName, fernetEncrypt(t, key, "attacker-controlled"))
	insertSecret(t, db, victimWS, secretName, fernetEncrypt(t, key, "owner-value"))

	resolved, err := resolver.ResolveInstanceEnvVars(victimInstance, []string{"API_KEY"})
	if err != nil {
		t.Fatalf("ResolveInstanceEnvVars() error = %v, want the owning workspace's secret", err)
	}
	if resolved["API_KEY"] != "owner-value" {
		t.Fatalf("ResolveInstanceEnvVars() API_KEY = %q, want %q", resolved["API_KEY"], "owner-value")
	}
}

// An instance row that does not exist has no workspace, so nothing can be
// resolved for it — the lookup must not fall back to matching on name alone.
func TestResolveInstanceEnvVarsRefusesUnknownInstance(t *testing.T) {
	db := resolverTestDB(t)
	resolver, key := newSchemaBackedResolver(t, db)

	const (
		unknownInstance = "33333333-3333-4333-8333-333333333333"
		strayWS         = "resolver-test-ws-stray"
	)
	secretName := fmt.Sprintf("mcp_instance_%s_API_KEY", unknownInstance)

	insertSecret(t, db, strayWS, secretName, fernetEncrypt(t, key, "stray-value"))

	_, err := resolver.ResolveInstanceEnvVars(unknownInstance, []string{"API_KEY"})
	if err == nil {
		t.Fatal("ResolveInstanceEnvVars() error = nil, want a failure for an instance that does not exist")
	}
}
