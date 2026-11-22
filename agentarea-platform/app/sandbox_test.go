package app

import (
	"context"
	"log/slog"
	"testing"

	knetguard "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/workspace"
	"github.com/agentarea/agentarea/agentarea-platform/internal/profiles/cluster/netguard"
)

func testOutbound(t *testing.T) *netguard.Outbound {
	t.Helper()
	trust, err := netguard.LoadTrust("")
	if err != nil {
		t.Fatal(err)
	}
	out, err := netguard.New(knetguard.Config{}, trust, slog.New(slog.DiscardHandler), netguard.Options{})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func TestSandboxObjectStoreUsesThePlatformCredentials(t *testing.T) {
	t.Setenv("AWS_ACCESS_KEY_ID", "aws-chain-key")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "aws-chain-secret") // pragma: allowlist secret

	client, err := sandboxObjectStore(context.Background(), workspace.RepositoryConfig{Region: "ru-1", AccessKey: "platform-key", SecretKey: "platform-secret"}, testOutbound(t))
	if err != nil {
		t.Fatalf("sandboxObjectStore: %v", err)
	}
	creds, err := client.Options().Credentials.Retrieve(context.Background())
	if err != nil {
		t.Fatalf("retrieve credentials: %v", err)
	}
	if creds.AccessKeyID != "platform-key" || creds.SecretAccessKey != "platform-secret" { // pragma: allowlist secret
		t.Fatalf("credentials = %q, want the AGENTAREA_S3_* pair, not the AWS chain", creds.AccessKeyID)
	}
}

func TestSandboxObjectStoreRefusesHalfAPair(t *testing.T) {
	if _, err := sandboxObjectStore(context.Background(), workspace.RepositoryConfig{Region: "ru-1", AccessKey: "platform-key"}, testOutbound(t)); err == nil {
		t.Fatal("sandboxObjectStore accepted an access key without a secret key")
	}
}
