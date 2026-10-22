package mcpstorage

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/s3"

	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestObjectStoreSignsWithTheConfiguredS3Keys(t *testing.T) {
	t.Setenv("AWS_ACCESS_KEY_ID", "")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "")
	t.Setenv("AWS_PROFILE", "")
	t.Setenv("AWS_CONFIG_FILE", t.TempDir()+"/none")
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", t.TempDir()+"/none")
	t.Setenv("AWS_EC2_METADATA_DISABLED", "true")

	store, err := NewObjectStore(context.Background(), workspace.RepositoryConfig{
		Bucket: "artifacts", Region: "us-east-1", Endpoint: "http://rustfs:9000",
		AccessKey: "rustfs-access", SecretKey: "rustfs-secret", // pragma: allowlist secret
	})
	if err != nil {
		t.Fatalf("NewObjectStore: %v", err)
	}
	creds, err := store.(*s3.Client).Options().Credentials.Retrieve(context.Background())
	if err != nil {
		t.Fatalf("retrieve credentials: %v", err)
	}
	if creds.AccessKeyID != "rustfs-access" || creds.SecretAccessKey != "rustfs-secret" { // pragma: allowlist secret
		t.Fatalf("store signs as %q, want the configured AGENTAREA_S3_ACCESS_KEY", creds.AccessKeyID)
	}
}

func TestObjectStoreRefusesHalfAKeyPair(t *testing.T) {
	_, err := NewObjectStore(context.Background(), workspace.RepositoryConfig{
		Bucket: "artifacts", Region: "us-east-1", AccessKey: "rustfs-access",
	})
	if err == nil {
		t.Fatal("NewObjectStore accepted an access key without its secret")
	}
}
