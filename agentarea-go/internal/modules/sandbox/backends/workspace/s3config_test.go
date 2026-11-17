package workspace

import (
	"context"
	"testing"
)

func TestS3ConfigUsesThePlatformCredentials(t *testing.T) {
	t.Setenv("AWS_ACCESS_KEY_ID", "aws-chain-key")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "aws-chain-secret") // pragma: allowlist secret

	cfg, err := S3Config(context.Background(), "ru-1", "platform-key", "platform-secret")
	if err != nil {
		t.Fatalf("S3Config: %v", err)
	}
	creds, err := cfg.Credentials.Retrieve(context.Background())
	if err != nil {
		t.Fatalf("retrieve credentials: %v", err)
	}
	if creds.AccessKeyID != "platform-key" || creds.SecretAccessKey != "platform-secret" { // pragma: allowlist secret
		t.Fatalf("credentials = %q, want the AGENTAREA_S3_* pair, not the AWS chain", creds.AccessKeyID)
	}
}

func TestS3ConfigRefusesHalfAPair(t *testing.T) {
	if _, err := S3Config(context.Background(), "ru-1", "platform-key", ""); err == nil {
		t.Fatal("S3Config accepted an access key without a secret key")
	}
}
