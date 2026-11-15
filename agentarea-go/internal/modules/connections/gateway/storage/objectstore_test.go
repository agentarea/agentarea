package storage

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/s3"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
)

func TestObjectStoreSignsWithTheConfiguredS3Keys(t *testing.T) {
	t.Setenv("AWS_ACCESS_KEY_ID", "aws-ambient")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "aws-ambient") // pragma: allowlist secret
	store, err := NewObjectStore(blob.Config{
		Region: "us-east-1", Endpoint: "http://rustfs:9000", ArtifactsBucket: "artifacts",
		AccessKey: "rustfs-access", SecretKey: "rustfs-secret", // pragma: allowlist secret
	})
	if err != nil {
		t.Fatalf("NewObjectStore: %v", err)
	}
	client, ok := store.(*s3.Client)
	if !ok {
		t.Fatalf("store is %T", store)
	}
	creds, err := client.Options().Credentials.Retrieve(context.Background())
	if err != nil {
		t.Fatalf("retrieve credentials: %v", err)
	}
	if creds.AccessKeyID != "rustfs-access" || creds.SecretAccessKey != "rustfs-secret" { // pragma: allowlist secret
		t.Fatalf("store signs as %q, want the configured AGENTAREA_S3_ACCESS_KEY", creds.AccessKeyID)
	}
	if !client.Options().UsePathStyle {
		t.Fatal("a custom endpoint is not addressed path-style")
	}
}

func TestObjectStoreRefusesHalfAKeyPair(t *testing.T) {
	if _, err := NewObjectStore(blob.Config{Region: "us-east-1", AccessKey: "rustfs-access"}); err == nil {
		t.Fatal("NewObjectStore accepted an access key without its secret")
	}
}
