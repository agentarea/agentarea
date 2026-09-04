package artifactstore

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"
)

type fakeS3Client struct {
	list         *s3.ListObjectsV2Output
	head         *s3.HeadObjectOutput
	listCalls    int
	headCalls    int
	putBytes     int64
	mu           sync.Mutex
	ledger       []byte
	ledgerETag   string
	ledgerWrites int
}

func (f *fakeS3Client) GetObject(_ context.Context, input *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if strings.HasSuffix(aws.ToString(input.Key), "_quota-ledger.json") {
		if f.ledger == nil {
			return nil, &smithy.GenericAPIError{Code: "NoSuchKey", Message: "missing"}
		}
		return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(append([]byte(nil), f.ledger...))), ETag: aws.String(f.ledgerETag)}, nil
	}
	return &s3.GetObjectOutput{Body: io.NopCloser(strings.NewReader(""))}, nil
}

func (f *fakeS3Client) HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	f.headCalls++
	return f.head, nil
}

func (f *fakeS3Client) PutObject(_ context.Context, input *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	if strings.HasSuffix(aws.ToString(input.Key), "_quota-ledger.json") {
		body, err := io.ReadAll(input.Body)
		if err != nil {
			return nil, err
		}
		f.mu.Lock()
		defer f.mu.Unlock()
		if input.IfNoneMatch != nil && f.ledger != nil {
			return nil, &smithy.GenericAPIError{Code: "PreconditionFailed", Message: "exists"}
		}
		if input.IfMatch != nil && (f.ledger == nil || aws.ToString(input.IfMatch) != f.ledgerETag) {
			return nil, &smithy.GenericAPIError{Code: "PreconditionFailed", Message: "etag mismatch"}
		}
		f.ledgerWrites++
		f.ledger = append([]byte(nil), body...)
		f.ledgerETag = fmt.Sprintf("etag-%d", f.ledgerWrites)
		return &s3.PutObjectOutput{ETag: aws.String(f.ledgerETag)}, nil
	}
	written, err := io.Copy(io.Discard, input.Body)
	if err != nil {
		return nil, err
	}
	f.mu.Lock()
	f.putBytes = written
	f.mu.Unlock()
	return &s3.PutObjectOutput{}, nil
}

func (f *fakeS3Client) seedPublishedArtifact(t *testing.T, workspaceID, taskID, artifactID string, size int64) {
	t.Helper()
	body, err := json.Marshal(quotaLedger{
		SchemaVersion: artifactLedgerSchemaVersion, WorkspaceID: workspaceID, TaskID: taskID,
		Entries: map[string]quotaEntry{artifactID: {Size: size, Published: true}},
	})
	if err != nil {
		t.Fatal(err)
	}
	f.ledger = body
	f.ledgerETag = "etag-seed"
}

func (f *fakeS3Client) ListObjectsV2(context.Context, *s3.ListObjectsV2Input, ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
	f.listCalls++
	return f.list, nil
}

func TestListReturnsVerifiedSourceMetadata(t *testing.T) {
	createdAt := time.Date(2026, 7, 31, 12, 0, 0, 0, time.UTC)
	hash := strings.Repeat("a", 64)
	id := deriveArtifactID("reports/report.pdf", hash)
	key := "root/workspaces/workspace-1/tasks/task-1/artifacts/" + id + "/report.pdf"
	client := &fakeS3Client{
		list: &s3.ListObjectsV2Output{
			Contents: []types.Object{{Key: aws.String(key), Size: aws.Int64(99)}},
		},
		head: &s3.HeadObjectOutput{
			ContentLength: aws.Int64(42),
			ContentType:   aws.String("application/pdf"),
			LastModified:  aws.Time(createdAt),
			Metadata: map[string]string{
				"sha256":      hash,
				"source-path": base64.RawURLEncoding.EncodeToString([]byte("reports/report.pdf")),
			},
		},
	}
	client.seedPublishedArtifact(t, "workspace-1", "task-1", id, 42)
	repository, err := New(Config{Bucket: "artifacts", Prefix: "root", MaxBytes: 256 * 1024 * 1024, MaxCount: 100, MaxTotalBytes: 1024 * 1024 * 1024}, client)
	if err != nil {
		t.Fatal(err)
	}

	items, err := repository.List(context.Background(), "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("items = %d, want 1", len(items))
	}
	item := items[0]
	if item.ID != id || item.Path != "reports/report.pdf" || item.Size != 42 || item.ContentType != "application/pdf" || item.SHA256 != hash {
		t.Fatalf("artifact = %+v", item)
	}
	if !item.CreatedAt.Equal(createdAt) || client.headCalls != 1 {
		t.Fatalf("created_at=%s head_calls=%d", item.CreatedAt, client.headCalls)
	}
}

func TestGetRejectsInvalidScopeBeforeS3(t *testing.T) {
	client := &fakeS3Client{list: &s3.ListObjectsV2Output{}}
	repository, err := New(Config{Bucket: "artifacts", MaxBytes: 256 * 1024 * 1024, MaxCount: 100, MaxTotalBytes: 1024 * 1024 * 1024}, client)
	if err != nil {
		t.Fatal(err)
	}

	_, _, err = repository.Get(
		context.Background(),
		"../other-workspace",
		"task-1",
		"art_0123456789abcdef0123456789abcdef",
	)
	if err == nil || errors.Is(err, ErrArtifactNotFound) {
		t.Fatalf("error = %v, want scope validation failure", err)
	}
	if client.listCalls != 0 {
		t.Fatalf("S3 list calls = %d, want 0", client.listCalls)
	}
}

func TestPublishStreamAcceptsArtifactBeyondLegacyInlineLimit(t *testing.T) {
	client := &fakeS3Client{}
	repository, err := New(Config{Bucket: "artifacts", MaxBytes: 32 * 1024 * 1024, MaxCount: 100, MaxTotalBytes: 1024 * 1024 * 1024}, client)
	if err != nil {
		t.Fatal(err)
	}
	content := bytes.Repeat([]byte("a"), 16*1024*1024+1)
	artifact, err := repository.PublishStream(
		context.Background(), "workspace-1", "task-1", "reports/large.bin",
		"application/octet-stream", bytes.NewReader(content), int64(len(content)),
	)
	if err != nil {
		t.Fatal(err)
	}
	if artifact.Size != int64(len(content)) || client.putBytes != int64(len(content)) {
		t.Fatalf("artifact size=%d uploaded=%d want=%d", artifact.Size, client.putBytes, len(content))
	}
}

func TestPublishStreamEnforcesCountQuotaAcrossConcurrentWriters(t *testing.T) {
	client := &fakeS3Client{}
	repository, err := New(Config{
		Bucket: "artifacts", MaxBytes: 1024, MaxCount: 1, MaxTotalBytes: 1024,
	}, client)
	if err != nil {
		t.Fatal(err)
	}

	start := make(chan struct{})
	errorsByWriter := make(chan error, 2)
	for _, sourcePath := range []string{"reports/a.txt", "reports/b.txt"} {
		go func(path string) {
			<-start
			_, publishErr := repository.PublishStream(
				context.Background(), "workspace-1", "task-1", path,
				"text/plain", strings.NewReader(path), int64(len(path)),
			)
			errorsByWriter <- publishErr
		}(sourcePath)
	}
	close(start)
	var successes, quotaFailures int
	for range 2 {
		publishErr := <-errorsByWriter
		switch {
		case publishErr == nil:
			successes++
		case errors.Is(publishErr, ErrArtifactQuotaExceeded):
			quotaFailures++
		default:
			t.Fatalf("unexpected publication error: %v", publishErr)
		}
	}
	if successes != 1 || quotaFailures != 1 {
		t.Fatalf("successes=%d quota_failures=%d, want one of each", successes, quotaFailures)
	}
}

func TestPublishStreamReclaimsExpiredQuotaReservation(t *testing.T) {
	client := &fakeS3Client{}
	staleID := deriveArtifactID("reports/stale.txt", strings.Repeat("a", 64))
	ledger, err := json.Marshal(quotaLedger{
		SchemaVersion: artifactLedgerSchemaVersion,
		WorkspaceID:   "workspace-1",
		TaskID:        "task-1",
		Entries: map[string]quotaEntry{
			staleID: {
				Size:             5,
				ReservationToken: "abandoned",
				ReservedUntil:    time.Now().UTC().Add(-time.Minute),
			},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	client.ledger = ledger
	client.ledgerETag = "etag-seed"
	repository, err := New(Config{Bucket: "artifacts", MaxBytes: 1024, MaxCount: 1, MaxTotalBytes: 1024}, client)
	if err != nil {
		t.Fatal(err)
	}

	artifact, err := repository.PublishStream(
		context.Background(), "workspace-1", "task-1", "reports/current.txt",
		"text/plain", strings.NewReader("current"), 7,
	)
	if err != nil {
		t.Fatal(err)
	}
	var stored quotaLedger
	if err := json.Unmarshal(client.ledger, &stored); err != nil {
		t.Fatal(err)
	}
	if _, exists := stored.Entries[staleID]; exists {
		t.Fatal("expired reservation still consumes artifact quota")
	}
	if entry := stored.Entries[artifact.ID]; !entry.Published || entry.Size != 7 {
		t.Fatalf("published artifact ledger entry = %+v", entry)
	}
}
