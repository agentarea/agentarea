package dataplaneconnect

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testDataPlaneID = "d1f74c88-cc04-4cc7-b4e3-6054901d572a"

func testConfig(t *testing.T, base string) Config {
	t.Helper()
	defaults := DefaultConfig()
	return Config{
		ControlPlaneURL:          base,
		DataPlaneID:              testDataPlaneID,
		ConnectorInstanceID:      "connector-a",
		IdentityFile:             filepath.Join(t.TempDir(), "identity.json"),
		EnrollmentTokenFile:      filepath.Join(t.TempDir(), "token"),
		AllowInsecureDevelopment: true,
		HTTPTimeout:              defaults.HTTPTimeout,
		HeartbeatInterval:        defaults.HeartbeatInterval,
		Capabilities:             Capabilities{},
	}
}

func TestJoinWritesSinglePrivateIdentity(t *testing.T) {
	var got EnrollmentRequest
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != EnrollmentExchangePath {
			t.Fatalf("path = %s", r.URL.Path)
		}
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Fatal(err)
		}
		json.NewEncoder(w).Encode(EnrollmentResponse{
			DataPlaneID:    testDataPlaneID,
			NodeID:         "61bcea34-6aa9-4e19-b3ed-08173f7af1bc",
			NodeCredential: "credential-value",
		})
	}))
	defer s.Close()
	cfg := testConfig(t, s.URL)
	cfg.DataPlaneID = ""
	cfg.ConnectorInstanceID = ""
	if err := os.WriteFile(cfg.EnrollmentTokenFile, []byte(" one-time-token\n"), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Join(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got.EnrollmentToken != "one-time-token" || got.DataPlaneID != "" || !strings.HasPrefix(string(got.ConnectorInstanceID), "connector-") {
		t.Fatalf("unexpected enrollment: %+v", got)
	}
	i, err := ReadIdentity(cfg.IdentityFile)
	if err != nil {
		t.Fatal(err)
	}
	if i.NodeCredential != "credential-value" {
		t.Fatal("credential not persisted")
	}
	if i.ConnectorInstanceID != got.ConnectorInstanceID {
		t.Fatal("generated connector instance ID not persisted")
	}
	info, err := os.Stat(cfg.IdentityFile)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("mode = %#o, want 0600", info.Mode().Perm())
	}
	dirInfo, err := os.Stat(filepath.Dir(cfg.IdentityFile))
	if err != nil {
		t.Fatal(err)
	}
	if dirInfo.Mode().Perm() != 0700 {
		t.Fatalf("identity directory mode = %#o, want 0700", dirInfo.Mode().Perm())
	}
}

func TestWriteIdentityCreatesPrivateParentDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "new", "state", "identity.json")
	if err := WriteIdentityAtomic(path, Identity{DataPlaneID: testDataPlaneID, ConnectorInstanceID: "connector", NodeCredential: "credential"}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(filepath.Dir(path))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0700 {
		t.Fatalf("directory mode = %#o, want 0700", info.Mode().Perm())
	}
}

func TestRejectsHTTPWithoutDevelopmentOptIn(t *testing.T) {
	cfg := testConfig(t, "http://example.test")
	cfg.AllowInsecureDevelopment = false
	if _, err := NewClient(cfg); err == nil || !strings.Contains(err.Error(), "HTTPS") {
		t.Fatalf("expected HTTPS error, got %v", err)
	}
}

func TestHeartbeatHasIdentityAndSeparateCapabilities(t *testing.T) {
	var got HeartbeatRequest
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/data-planes/"+testDataPlaneID+"/heartbeat" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer node-secret" {
			t.Fatalf("missing bearer auth")
		}
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Fatal(err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer s.Close()
	cfg := testConfig(t, s.URL)
	identity := Identity{
		DataPlaneID:         cfg.DataPlaneID,
		ConnectorInstanceID: "connector-persisted",
		NodeCredential:      "node-secret",
	}
	if err := WriteIdentityAtomic(cfg.IdentityFile, identity); err != nil {
		t.Fatal(err)
	}
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Heartbeat(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got.ProtocolVersion != ProtocolVersion || got.AgentVersion != cfg.AgentVersion || got.ConnectorInstanceID != "connector-persisted" || got.Capabilities.MCP || got.Capabilities.Sandbox {
		t.Fatalf("unexpected heartbeat: %+v", got)
	}
}

func TestJoinReusesPersistedConnectorInstanceID(t *testing.T) {
	var got EnrollmentRequest
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Fatal(err)
		}
		_ = json.NewEncoder(w).Encode(EnrollmentResponse{DataPlaneID: testDataPlaneID, NodeID: "61bcea34-6aa9-4e19-b3ed-08173f7af1bc", NodeCredential: "new-credential"})
	}))
	defer s.Close()
	cfg := testConfig(t, s.URL)
	cfg.ConnectorInstanceID = ""
	if err := WriteIdentityAtomic(cfg.IdentityFile, Identity{DataPlaneID: cfg.DataPlaneID, ConnectorInstanceID: "persisted-connector", NodeCredential: "old-credential"}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(cfg.EnrollmentTokenFile, []byte("one-time-token"), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Join(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got.ConnectorInstanceID != "persisted-connector" {
		t.Fatalf("connector ID = %q, want persisted value", got.ConnectorInstanceID)
	}
}

func TestHTTPFailureDoesNotExposeResponseBody(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "credential-and-token", http.StatusUnauthorized)
	}))
	defer s.Close()
	cfg := testConfig(t, s.URL)
	if err := os.WriteFile(cfg.EnrollmentTokenFile, []byte("enrollment-token"), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := NewClient(cfg)
	if err != nil {
		t.Fatal(err)
	}
	err = c.Join(context.Background())
	if err == nil || !strings.Contains(err.Error(), "status 401") || strings.Contains(err.Error(), "credential-and-token") {
		t.Fatalf("unexpected response error: %v", err)
	}
}

func TestRedactCredentials(t *testing.T) {
	got := Redact("token enrollment-token and node-secret", "enrollment-token", "node-secret")
	if strings.Contains(got, "enrollment-token") || strings.Contains(got, "node-secret") || !strings.Contains(got, "[REDACTED]") {
		t.Fatalf("redaction failed: %q", got)
	}
}
