package workspace

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

func TestRepositoryRejectsCrossTaskObjectBeforeSigning(t *testing.T) {
	repository, storage, ref, manifest := repositoryFixture(t)
	manifest.Entries[0].ObjectURI = "s3://trusted/root/workspaces/ws-1/tasks/task-other/objects/" + manifest.Entries[0].SHA256
	ref = storage.replaceManifest(t, repository, ref, manifest)
	storage.putJSON(repository.pointerKey(ref), ref, "current-cross")

	_, _, err := repository.PrepareHydration(context.Background(), ref)
	if err == nil || !strings.Contains(err.Error(), "authorized task prefix") {
		t.Fatalf("PrepareHydration() error = %v", err)
	}
	if storage.presignCalls != 0 {
		t.Fatalf("presigner called %d times for unauthorized ref", storage.presignCalls)
	}
}

func TestRepositoryStaleCurrentETagCannotCommit(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	_, base, err := repository.PrepareHydration(context.Background(), ref)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := repository.PlanWriteback(context.Background(), ref, base, []ChangeDescriptor{{RelativePath: "src/a.py", Deleted: true}})
	if err != nil {
		t.Fatal(err)
	}
	storage.putJSON(repository.pointerKey(ref), ref, "current-reassigned")

	_, _, err = repository.VerifyAndCommit(context.Background(), plan)
	if err == nil || !errorsIs(err, ErrWorkspaceConflict) {
		t.Fatalf("VerifyAndCommit() error = %v", err)
	}
}

func TestRepositoryTombstoneCommitUsesConditionalCurrentPointer(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	_, base, err := repository.PrepareHydration(context.Background(), ref)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := repository.PlanWriteback(context.Background(), ref, base, []ChangeDescriptor{{RelativePath: "src/a.py", Deleted: true}})
	if err != nil {
		t.Fatal(err)
	}
	next, changed, err := repository.VerifyAndCommit(context.Background(), plan)
	if err != nil {
		t.Fatal(err)
	}
	if next.Generation != ref.Generation+1 || len(changed) != 1 || !changed[0].Deleted || changed[0].RelativePath != "src/a.py" {
		t.Fatalf("next=%#v changed=%#v", next, changed)
	}
	if storage.lastPointerIfMatch != "current-1" {
		t.Fatalf("current pointer If-Match = %q", storage.lastPointerIfMatch)
	}
}

func TestRepositoryRecoversCommittedDirectSuccessor(t *testing.T) {
	repository, _, ref, _ := repositoryFixture(t)
	_, base, err := repository.PrepareHydration(context.Background(), ref)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := repository.PlanWriteback(context.Background(), ref, base, []ChangeDescriptor{{RelativePath: "src/a.py", Deleted: true}})
	if err != nil {
		t.Fatal(err)
	}
	wantRef, wantChanged, err := repository.VerifyAndCommit(context.Background(), plan)
	if err != nil {
		t.Fatal(err)
	}

	gotRef, gotChanged, committed, err := repository.RecoverCommittedSuccessor(context.Background(), ref)
	if err != nil {
		t.Fatal(err)
	}
	if !committed || gotRef != wantRef || len(gotChanged) != 1 || gotChanged[0] != wantChanged[0] {
		t.Fatalf("recovery = (%#v, %#v, %t), want (%#v, %#v, true)", gotRef, gotChanged, committed, wantRef, wantChanged)
	}
}

func TestRepositoryDoesNotMistakeUnchangedOrUnrelatedGenerationForCommit(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	if _, _, committed, err := repository.RecoverCommittedSuccessor(context.Background(), ref); err != nil || committed {
		t.Fatalf("unchanged recovery committed = %t, error = %v", committed, err)
	}

	unrelated := ref
	unrelated.Generation += 2
	unrelated.BaseGeneration = ref.Generation + 1
	unrelated.ManifestSHA256 = strings.Repeat("b", 64)
	unrelated.ManifestURI = repository.objectURI(repository.manifestKey(unrelated.WorkspaceID, unrelated.TaskID, unrelated.Generation, unrelated.ManifestSHA256))
	storage.putJSON(repository.pointerKey(ref), unrelated, "current-unrelated")
	if _, _, committed, err := repository.RecoverCommittedSuccessor(context.Background(), ref); err == nil || committed || !errorsIs(err, ErrWorkspaceConflict) {
		t.Fatalf("unrelated recovery committed = %t, error = %v", committed, err)
	}
}

func TestManifestRefRejectsTraversalAndSignedURI(t *testing.T) {
	ref := ManifestRef{
		SchemaVersion: SchemaVersion, WorkspaceID: "ws-1", TaskID: "task-1", Generation: 1,
		BaseGeneration: 0, FencingToken: 1, ManifestSHA256: strings.Repeat("a", 64),
		ManifestURI: "s3://trusted/root/workspaces/ws-1/tasks/task-1/manifests/1.json?X-Amz-Signature=secret",
	}
	if err := ref.Validate(); err == nil {
		t.Fatal("signed manifest URI was accepted")
	}
	for _, candidate := range []string{"/absolute", "../escape", "a/../b", `a\b`} {
		if _, err := NormalizeRelativePath(candidate); err == nil {
			t.Fatalf("path %q was accepted", candidate)
		}
	}
}

func TestConfigFromEnvUsesPlatformStorageFallbacksAndAlignedQuotas(t *testing.T) {
	t.Setenv("SANDBOX_WORKSPACE_S3_BUCKET", "")
	t.Setenv("SANDBOX_WORKSPACE_S3_REGION", "")
	t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", "")
	t.Setenv("SANDBOX_WORKSPACE_MAX_FILES", "")
	t.Setenv("SANDBOX_WORKSPACE_MAX_FILE_BYTES", "")
	t.Setenv("SANDBOX_WORKSPACE_MAX_BYTES", "")
	t.Setenv("SANDBOX_WORKSPACE_SIGNED_URL_TTL", "")
	t.Setenv("ARTIFACTS_BUCKET_NAME", "artifacts-fallback")
	t.Setenv("AWS_REGION", "eu-west-2")
	t.Setenv("AWS_ENDPOINT_URL", "http://rustfs:9000/")

	cfg := ConfigFromEnv()
	if cfg.Bucket != "artifacts-fallback" || cfg.Region != "eu-west-2" || cfg.Endpoint != "http://rustfs:9000" {
		t.Fatalf("storage fallback config = %#v", cfg)
	}
	if cfg.MaxFiles != 10_000 || cfg.MaxFileBytes != 256*1024*1024 || cfg.MaxBytes != 2*1024*1024*1024 {
		t.Fatalf("workspace quota defaults = %#v", cfg)
	}
	if cfg.SignedURLTTL != time.Hour {
		t.Fatalf("signed URL TTL = %s, want %s", cfg.SignedURLTTL, time.Hour)
	}
}

func TestConfigFromEnvPrefersWorkspaceOverrides(t *testing.T) {
	t.Setenv("ARTIFACTS_BUCKET_NAME", "platform-bucket")
	t.Setenv("AWS_REGION", "platform-region")
	t.Setenv("AWS_ENDPOINT_URL", "http://platform.invalid")
	t.Setenv("SANDBOX_WORKSPACE_S3_BUCKET", "workspace-bucket")
	t.Setenv("SANDBOX_WORKSPACE_S3_REGION", "workspace-region")
	t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", "http://workspace.invalid/")

	cfg := ConfigFromEnv()
	if cfg.Bucket != "workspace-bucket" || cfg.Region != "workspace-region" || cfg.Endpoint != "http://workspace.invalid" {
		t.Fatalf("workspace override config = %#v", cfg)
	}
}

func TestRepositoryReleaseLeaseExpiresMatchingToken(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	if err := repository.ReleaseLease(context.Background(), ref); err != nil {
		t.Fatal(err)
	}
	storage.mu.Lock()
	leaseObject := storage.objects[repository.leaseKey(ref)]
	storage.mu.Unlock()
	var lease leaseRecord
	if err := json.Unmarshal(leaseObject.body, &lease); err != nil {
		t.Fatal(err)
	}
	if lease.FencingToken != ref.FencingToken || lease.Owner != "runner-1" || lease.ExpiresAt.After(time.Now().UTC()) {
		t.Fatalf("released lease = %#v", lease)
	}
}

func TestRepositoryRenewLeaseExtendsMatchingTokenWithConditionalWrite(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	before := time.Now().UTC()
	if err := repository.RenewLease(context.Background(), ref, 2*time.Hour); err != nil {
		t.Fatal(err)
	}
	storage.mu.Lock()
	leaseObject := storage.objects[repository.leaseKey(ref)]
	storage.mu.Unlock()
	var lease leaseRecord
	if err := json.Unmarshal(leaseObject.body, &lease); err != nil {
		t.Fatal(err)
	}
	if lease.Owner != "runner-1" || lease.FencingToken != ref.FencingToken || lease.ExpiresAt.Before(before.Add(2*time.Hour-time.Second)) {
		t.Fatalf("renewed lease = %#v", lease)
	}
}

func TestRepositoryRenewLeaseFailsClosedForNewerFencingToken(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	newer := leaseRecord{Owner: "runner-2", FencingToken: ref.FencingToken + 1, ExpiresAt: time.Now().UTC().Add(time.Hour)}
	storage.putJSON(repository.leaseKey(ref), newer, "lease-2")

	err := repository.RenewLease(context.Background(), ref, time.Hour)
	if err == nil || !errorsIs(err, ErrWorkspaceConflict) {
		t.Fatalf("RenewLease() error = %v", err)
	}
	storage.mu.Lock()
	leaseObject := storage.objects[repository.leaseKey(ref)]
	storage.mu.Unlock()
	var preserved leaseRecord
	if err := json.Unmarshal(leaseObject.body, &preserved); err != nil {
		t.Fatal(err)
	}
	if preserved != newer {
		t.Fatalf("newer lease changed: got %#v want %#v", preserved, newer)
	}
}

func TestRepositoryRenewLeaseConditionalWriteCannotOverwriteRacingOwner(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	newer := leaseRecord{Owner: "runner-2", FencingToken: ref.FencingToken + 1, ExpiresAt: time.Now().UTC().Add(time.Hour)}
	newerBody, err := json.Marshal(newer)
	if err != nil {
		t.Fatal(err)
	}
	storage.conditionalRaceKey = repository.leaseKey(ref)
	storage.conditionalRaceObject = fakeObject{body: newerBody, etag: "lease-2"}

	err = repository.RenewLease(context.Background(), ref, time.Hour)
	if err == nil || !errorsIs(err, ErrWorkspaceConflict) {
		t.Fatalf("RenewLease() error = %v", err)
	}
	storage.mu.Lock()
	leaseObject := storage.objects[repository.leaseKey(ref)]
	storage.mu.Unlock()
	var preserved leaseRecord
	if err := json.Unmarshal(leaseObject.body, &preserved); err != nil {
		t.Fatal(err)
	}
	if preserved != newer {
		t.Fatalf("racing lease changed: got %#v want %#v", preserved, newer)
	}
}

func TestRepositoryReleaseLeaseCannotExpireNewerToken(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	newer := leaseRecord{Owner: "runner-2", FencingToken: ref.FencingToken + 1, ExpiresAt: time.Now().UTC().Add(time.Hour)}
	storage.putJSON(repository.leaseKey(ref), newer, "lease-2")

	err := repository.ReleaseLease(context.Background(), ref)
	if err == nil || !errorsIs(err, ErrWorkspaceConflict) {
		t.Fatalf("ReleaseLease() error = %v", err)
	}
	storage.mu.Lock()
	leaseObject := storage.objects[repository.leaseKey(ref)]
	storage.mu.Unlock()
	var preserved leaseRecord
	if err := json.Unmarshal(leaseObject.body, &preserved); err != nil {
		t.Fatal(err)
	}
	if preserved.Owner != newer.Owner || preserved.FencingToken != newer.FencingToken || !preserved.ExpiresAt.Equal(newer.ExpiresAt) {
		t.Fatalf("newer lease changed: got %#v want %#v", preserved, newer)
	}
}

func TestRepositoryReleaseLeaseConditionalWriteCannotOverwriteRacingOwner(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	newer := leaseRecord{Owner: "runner-2", FencingToken: ref.FencingToken + 1, ExpiresAt: time.Now().UTC().Add(time.Hour)}
	newerBody, err := json.Marshal(newer)
	if err != nil {
		t.Fatal(err)
	}
	storage.mu.Lock()
	storage.conditionalRaceKey = repository.leaseKey(ref)
	storage.conditionalRaceObject = fakeObject{body: newerBody, etag: "lease-2"}
	storage.mu.Unlock()

	err = repository.ReleaseLease(context.Background(), ref)
	if err == nil || !errorsIs(err, ErrWorkspaceConflict) {
		t.Fatalf("ReleaseLease() error = %v", err)
	}
	storage.mu.Lock()
	leaseObject := storage.objects[repository.leaseKey(ref)]
	storage.mu.Unlock()
	var preserved leaseRecord
	if err := json.Unmarshal(leaseObject.body, &preserved); err != nil {
		t.Fatal(err)
	}
	if preserved.Owner != newer.Owner || preserved.FencingToken != newer.FencingToken || !preserved.ExpiresAt.Equal(newer.ExpiresAt) {
		t.Fatalf("racing lease changed: got %#v want %#v", preserved, newer)
	}
}

func TestRepositoryRejectsFileOverPerFileQuota(t *testing.T) {
	repository, _, ref, base := repositoryFixture(t)
	repository.cfg.MaxFileBytes = 4
	_, err := repository.PlanWriteback(context.Background(), ref, base, []ChangeDescriptor{{
		RelativePath: "large.bin",
		SHA256:       strings.Repeat("a", 64),
		Size:         5,
	}})
	if err == nil || !errorsIs(err, ErrQuotaExceeded) {
		t.Fatalf("PlanWriteback() error = %v", err)
	}
}

func TestRepositoryRejectsResultingWorkspaceOverTotalQuotaWithoutMutation(t *testing.T) {
	repository, storage, ref, base := repositoryFixture(t)
	repository.cfg.MaxBytes = 10
	base.Entries[0].Size = 10
	storage.mu.Lock()
	pointerBefore := storage.objects[repository.pointerKey(ref)]
	storage.mu.Unlock()

	plan, err := repository.PlanWriteback(context.Background(), ref, base, []ChangeDescriptor{{
		RelativePath: "second.bin",
		SHA256:       strings.Repeat("b", 64),
		Size:         1,
	}})
	if plan != nil || err == nil || !errorsIs(err, ErrQuotaExceeded) {
		t.Fatalf("PlanWriteback() plan = %#v, error = %v", plan, err)
	}
	storage.mu.Lock()
	pointerAfter := storage.objects[repository.pointerKey(ref)]
	storage.mu.Unlock()
	if pointerAfter.etag != pointerBefore.etag || !bytes.Equal(pointerAfter.body, pointerBefore.body) {
		t.Fatal("workspace current pointer changed after quota rejection")
	}
}

func TestRepositoryStoresAndVerifiesContentAddressedExecutionOutput(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	content := []byte("bounded stdout\n")
	entry, err := repository.StoreExecutionOutput(context.Background(), ref, "sexec_123", "stdout", content)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(content)
	wantHash := hex.EncodeToString(digest[:])
	if entry.SHA256 != wantHash || entry.Size != int64(len(content)) || entry.RelativePath != ".agentarea/executions/sexec_123/stdout.txt" {
		t.Fatalf("execution output entry = %#v", entry)
	}
	stored := storage.objects[repository.keyFromURI(entry.ObjectURI)]
	if !bytes.Equal(stored.body, content) || stored.metadata["sha256"] != wantHash {
		t.Fatalf("stored execution output = %#v", stored)
	}

	// Reusing an existing content-addressed object is safe only after its body
	// and declared identity have both been verified.
	if _, err := repository.StoreExecutionOutput(context.Background(), ref, "sexec_456", "stderr", content); err != nil {
		t.Fatalf("idempotent content-addressed store failed: %v", err)
	}
}

func TestRepositoryRejectsExecutionOutputIdentityCollision(t *testing.T) {
	repository, storage, ref, _ := repositoryFixture(t)
	content := []byte("expected")
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	key := repository.taskPrefix(ref.WorkspaceID, ref.TaskID) + "/objects/" + hash
	storage.conditionalRaceKey = key
	storage.conditionalRaceObject = fakeObject{
		body:     []byte("tampered"),
		etag:     "tampered-etag",
		metadata: map[string]string{"sha256": hash},
	}
	if _, err := repository.StoreExecutionOutput(context.Background(), ref, "sexec_789", "stdout", content); err == nil {
		t.Fatal("content-addressed identity collision was accepted")
	}
}

func repositoryFixture(t *testing.T) (*Repository, *fakeS3, ManifestRef, Manifest) {
	t.Helper()
	storage := newFakeS3()
	repository, err := NewRepository(RepositoryConfig{Bucket: "trusted", Prefix: "root", SignedURLTTL: time.Minute, MaxFiles: 100, MaxBytes: 1024 * 1024}, storage, storage)
	if err != nil {
		t.Fatal(err)
	}
	contentHash := sha256.Sum256([]byte("print('ok')\n"))
	manifest := Manifest{
		SchemaVersion: SchemaVersion, WorkspaceID: "ws-1", TaskID: "task-1", Generation: 1, BaseGeneration: 0, FencingToken: 7,
		Entries: []Entry{{
			RelativePath: "src/a.py", ObjectURI: "s3://trusted/root/workspaces/ws-1/tasks/task-1/objects/" + hex.EncodeToString(contentHash[:]),
			ObjectVersionOrETag: "object-1", SHA256: hex.EncodeToString(contentHash[:]), Size: int64(len("print('ok')\n")), ContentType: "text/x-python", Mode: 0o600,
		}},
	}
	manifestBytes, _ := json.Marshal(manifest)
	manifestHash := sha256.Sum256(manifestBytes)
	ref := ManifestRef{
		SchemaVersion: SchemaVersion, WorkspaceID: "ws-1", TaskID: "task-1", Generation: 1, BaseGeneration: 0, FencingToken: 7,
		ManifestSHA256: hex.EncodeToString(manifestHash[:]),
	}
	ref.ManifestURI = repository.objectURI(repository.manifestKey(ref.WorkspaceID, ref.TaskID, ref.Generation, ref.ManifestSHA256))
	storage.put(repository.keyFromURI(ref.ManifestURI), manifestBytes, "manifest-1", nil)
	storage.put(repository.keyFromURI(manifest.Entries[0].ObjectURI), []byte("print('ok')\n"), "object-1", map[string]string{"sha256": manifest.Entries[0].SHA256})
	storage.putJSON(repository.pointerKey(ref), ref, "current-1")
	storage.putJSON(repository.leaseKey(ref), leaseRecord{Owner: "runner-1", FencingToken: ref.FencingToken, ExpiresAt: time.Now().UTC().Add(time.Hour)}, "lease-1")
	return repository, storage, ref, manifest
}

func (r *Repository) keyFromURI(uri string) string {
	return strings.TrimPrefix(uri, "s3://"+r.cfg.Bucket+"/")
}
func (r *Repository) pointerKey(ref ManifestRef) string {
	return r.taskPrefix(ref.WorkspaceID, ref.TaskID) + "/current.json"
}
func (r *Repository) leaseKey(ref ManifestRef) string {
	return r.taskPrefix(ref.WorkspaceID, ref.TaskID) + "/lease.json"
}

func errorsIs(err, target error) bool { return strings.Contains(err.Error(), target.Error()) }

type fakeObject struct {
	body     []byte
	etag     string
	metadata map[string]string
	version  string
}

type fakeS3 struct {
	mu                    sync.Mutex
	objects               map[string]fakeObject
	presignCalls          int
	lastPointerIfMatch    string
	conditionalRaceKey    string
	conditionalRaceObject fakeObject
}

func newFakeS3() *fakeS3 { return &fakeS3{objects: map[string]fakeObject{}} }

func (f *fakeS3) put(key string, body []byte, etag string, metadata map[string]string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.objects[key] = fakeObject{body: append([]byte(nil), body...), etag: etag, metadata: metadata}
}

func (f *fakeS3) putJSON(key string, value any, etag string) {
	body, _ := json.Marshal(value)
	f.put(key, body, etag, nil)
}

func (f *fakeS3) replaceManifest(t *testing.T, repository *Repository, old ManifestRef, manifest Manifest) ManifestRef {
	t.Helper()
	body, _ := json.Marshal(manifest)
	hash := sha256.Sum256(body)
	old.ManifestSHA256 = hex.EncodeToString(hash[:])
	old.ManifestURI = repository.objectURI(repository.manifestKey(old.WorkspaceID, old.TaskID, old.Generation, old.ManifestSHA256))
	f.put(repository.keyFromURI(old.ManifestURI), body, "manifest-replaced", nil)
	return old
}

func (f *fakeS3) GetObject(_ context.Context, input *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	object, ok := f.objects[aws.ToString(input.Key)]
	if !ok {
		return nil, fmt.Errorf("not found")
	}
	return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(object.body)), ETag: aws.String(object.etag), Metadata: object.metadata, VersionId: aws.String(object.version)}, nil
}

func (f *fakeS3) HeadObject(_ context.Context, input *s3.HeadObjectInput, _ ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	object, ok := f.objects[aws.ToString(input.Key)]
	if !ok {
		return nil, fmt.Errorf("not found")
	}
	return &s3.HeadObjectOutput{ContentLength: aws.Int64(int64(len(object.body))), ETag: aws.String(object.etag), Metadata: object.metadata, VersionId: aws.String(object.version)}, nil
}

func (f *fakeS3) PutObject(_ context.Context, input *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	key := aws.ToString(input.Key)
	if key == f.conditionalRaceKey {
		f.objects[key] = f.conditionalRaceObject
		f.conditionalRaceKey = ""
		f.conditionalRaceObject = fakeObject{}
	}
	current, exists := f.objects[key]
	if input.IfNoneMatch != nil && aws.ToString(input.IfNoneMatch) == "*" && exists {
		return nil, fmt.Errorf("precondition failed")
	}
	if input.IfMatch != nil {
		if !exists || current.etag != aws.ToString(input.IfMatch) {
			return nil, fmt.Errorf("precondition failed")
		}
		if strings.HasSuffix(key, "/current.json") {
			f.lastPointerIfMatch = aws.ToString(input.IfMatch)
		}
	}
	body, err := io.ReadAll(input.Body)
	if err != nil {
		return nil, err
	}
	etag := fmt.Sprintf("etag-%x", sha256.Sum256(body))
	f.objects[key] = fakeObject{body: body, etag: etag, metadata: input.Metadata}
	return &s3.PutObjectOutput{ETag: aws.String(etag)}, nil
}

func (f *fakeS3) PresignGetObject(_ context.Context, _ *s3.GetObjectInput, _ ...func(*s3.PresignOptions)) (*v4.PresignedHTTPRequest, error) {
	f.presignCalls++
	return &v4.PresignedHTTPRequest{URL: "https://object-storage.invalid/get", Method: http.MethodGet, SignedHeader: http.Header{}}, nil
}

func (f *fakeS3) PresignPutObject(_ context.Context, _ *s3.PutObjectInput, _ ...func(*s3.PresignOptions)) (*v4.PresignedHTTPRequest, error) {
	f.presignCalls++
	return &v4.PresignedHTTPRequest{URL: "https://object-storage.invalid/put", Method: http.MethodPut, SignedHeader: http.Header{}}, nil
}
