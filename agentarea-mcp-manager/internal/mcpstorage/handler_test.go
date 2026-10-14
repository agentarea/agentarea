package mcpstorage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/models"
)

type storedObject struct {
	data        []byte
	etag        string
	contentType string
	metadata    map[string]string
	checksum    string
}

type fakeStore struct {
	mu      sync.Mutex
	objects map[string]storedObject
	counter int
	puts    []*s3.PutObjectInput
}

func newFakeStore() *fakeStore { return &fakeStore{objects: map[string]storedObject{}} }

func (f *fakeStore) GetObject(_ context.Context, in *s3.GetObjectInput, _ ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	object, ok := f.objects[aws.ToString(in.Key)]
	if !ok {
		return nil, &smithy.GenericAPIError{Code: "NoSuchKey"}
	}
	return &s3.GetObjectOutput{Body: io.NopCloser(bytes.NewReader(object.data)), ETag: aws.String(object.etag), ContentType: aws.String(object.contentType), ContentLength: aws.Int64(int64(len(object.data)))}, nil
}

func (f *fakeStore) HeadObject(_ context.Context, in *s3.HeadObjectInput, _ ...func(*s3.Options)) (*s3.HeadObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	object, ok := f.objects[aws.ToString(in.Key)]
	if !ok {
		return nil, &smithy.GenericAPIError{Code: "NotFound"}
	}
	return &s3.HeadObjectOutput{ETag: aws.String(object.etag), ContentType: aws.String(object.contentType), ContentLength: aws.Int64(int64(len(object.data)))}, nil
}

func (f *fakeStore) PutObject(_ context.Context, in *s3.PutObjectInput, _ ...func(*s3.Options)) (*s3.PutObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.puts = append(f.puts, in)
	key := aws.ToString(in.Key)
	current, exists := f.objects[key]
	switch {
	case in.IfNoneMatch != nil && exists:
		return nil, &smithy.GenericAPIError{Code: "PreconditionFailed"}
	case in.IfMatch != nil && !exists:
		return nil, &smithy.GenericAPIError{Code: "NoSuchKey"}
	case in.IfMatch != nil && aws.ToString(in.IfMatch) != current.etag:
		return nil, &smithy.GenericAPIError{Code: "PreconditionFailed"}
	}
	data, _ := io.ReadAll(in.Body)
	f.counter++
	etag := fmt.Sprintf(`"etag-%d"`, f.counter)
	f.objects[key] = storedObject{data: data, etag: etag, contentType: aws.ToString(in.ContentType), metadata: in.Metadata, checksum: aws.ToString(in.ChecksumSHA256)}
	return &s3.PutObjectOutput{ETag: aws.String(etag)}, nil
}

func (f *fakeStore) DeleteObject(_ context.Context, in *s3.DeleteObjectInput, _ ...func(*s3.Options)) (*s3.DeleteObjectOutput, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	key := aws.ToString(in.Key)
	if current, ok := f.objects[key]; ok && in.IfMatch != nil && aws.ToString(in.IfMatch) != current.etag {
		return nil, &smithy.GenericAPIError{Code: "PreconditionFailed"}
	}
	delete(f.objects, key)
	return &s3.DeleteObjectOutput{}, nil
}

// ListObjectsV2 pages two keys at a time so a caller that stops after the
// first page is caught.
func (f *fakeStore) ListObjectsV2(_ context.Context, in *s3.ListObjectsV2Input, _ ...func(*s3.Options)) (*s3.ListObjectsV2Output, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	var keys []string
	for key := range f.objects {
		if strings.HasPrefix(key, aws.ToString(in.Prefix)) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	start := 0
	if in.ContinuationToken != nil {
		start, _ = strconv.Atoi(*in.ContinuationToken)
	}
	end := min(start+2, len(keys))
	out := &s3.ListObjectsV2Output{IsTruncated: aws.Bool(end < len(keys))}
	if end < len(keys) {
		out.NextContinuationToken = aws.String(strconv.Itoa(end))
	}
	modified := time.Unix(1_800_000_000, 0)
	for _, key := range keys[start:end] {
		object := f.objects[key]
		out.Contents = append(out.Contents, types.Object{Key: aws.String(key), Size: aws.Int64(int64(len(object.data))), ETag: aws.String(object.etag), LastModified: &modified})
	}
	return out, nil
}

type fakeInstances map[string]*models.MCPServerInstance

func (f fakeInstances) Instance(_ context.Context, id string) (*models.MCPServerInstance, error) {
	if instance, ok := f[id]; ok {
		return instance, nil
	}
	return nil, ErrInstanceNotFound
}

const testPrefix = "workspaces/ws-1/apps/inst-1/"

var testSecret = []byte("0123456789abcdef0123456789abcdef") // pragma: allowlist secret

func sign(t *testing.T, secret []byte, workspaceID, instanceID string) string {
	t.Helper()
	token, err := activationauth.Sign(secret, activationauth.ScopeStorage, identity(workspaceID, instanceID), activationauth.BodySHA256(nil), time.Now(), time.Hour)
	if err != nil {
		t.Fatalf("Sign() error = %v", err)
	}
	return token
}

type harness struct {
	t      *testing.T
	server *httptest.Server
	store  *fakeStore
	token  string
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	store := newFakeStore()
	instances := fakeInstances{
		"inst-1": {InstanceID: "inst-1", WorkspaceID: "ws-1", JSONSpec: map[string]any{"storage": map[string]any{"enabled": true}}},
		"inst-2": {InstanceID: "inst-2", WorkspaceID: "ws-1", JSONSpec: map[string]any{}},
		"inst-3": {InstanceID: "inst-3", WorkspaceID: "ws-1", JSONSpec: map[string]any{"storage": map[string]any{"enabled": true}}},
	}
	handler, err := NewHandler(testSecret, "artifacts", store, instances, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatalf("NewHandler() error = %v", err)
	}
	handler.maxSize = 64
	// Served bare, as gin serves it: a ServeMux would clean ".." away before
	// the handler saw it.
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return &harness{t: t, server: server, store: store, token: sign(t, testSecret, "ws-1", "inst-1")}
}

func (h *harness) do(method, rawPath string, body []byte, headers map[string]string) *http.Response {
	h.t.Helper()
	return h.doAt("inst-1", method, rawPath, body, headers)
}

func (h *harness) doAt(instanceID, method, rawPath string, body []byte, headers map[string]string) *http.Response {
	h.t.Helper()
	base := "/mcp/" + instanceID + "/storage"
	request, err := http.NewRequest(method, h.server.URL+base+rawPath, bytes.NewReader(body))
	if err != nil {
		h.t.Fatalf("NewRequest() error = %v", err)
	}
	request.URL.RawPath = base + rawPath
	request.Header.Set("Authorization", "Bearer "+h.token)
	for key, value := range headers {
		if value == "" {
			request.Header.Del(key)
			continue
		}
		request.Header.Set(key, value)
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		h.t.Fatalf("%s %s error = %v", method, rawPath, err)
	}
	h.t.Cleanup(func() { _ = response.Body.Close() })
	return response
}

func expectStatus(t *testing.T, response *http.Response, want int) {
	t.Helper()
	if response.StatusCode != want {
		body, _ := io.ReadAll(response.Body)
		t.Fatalf("%s %s = %d (%s), want %d", response.Request.Method, response.Request.URL.Path, response.StatusCode, body, want)
	}
}

func TestCompareAndSwapLifecycle(t *testing.T) {
	h := newHarness(t)

	expectStatus(t, h.do(http.MethodPut, "/objects/db/app.sqlite", []byte("v1"), nil), http.StatusPreconditionRequired)

	created := h.do(http.MethodPut, "/objects/db/app.sqlite", []byte("v1"), map[string]string{"If-None-Match": "*"})
	expectStatus(t, created, http.StatusOK)
	first := created.Header.Get("ETag")
	if first == "" {
		t.Fatal("create returned no ETag")
	}
	expectStatus(t, h.do(http.MethodPut, "/objects/db/app.sqlite", []byte("again"), map[string]string{"If-None-Match": "*"}), http.StatusPreconditionFailed)

	updated := h.do(http.MethodPut, "/objects/db/app.sqlite", []byte("v2"), map[string]string{"If-Match": first})
	expectStatus(t, updated, http.StatusOK)
	second := updated.Header.Get("ETag")
	expectStatus(t, h.do(http.MethodPut, "/objects/db/app.sqlite", []byte("lost"), map[string]string{"If-Match": first}), http.StatusPreconditionFailed)

	read := h.do(http.MethodGet, "/objects/db/app.sqlite", nil, nil)
	expectStatus(t, read, http.StatusOK)
	if body, _ := io.ReadAll(read.Body); string(body) != "v2" || read.Header.Get("ETag") != second {
		t.Fatalf("GET = %q etag %q, want v2 etag %q", body, read.Header.Get("ETag"), second)
	}
	head := h.do(http.MethodHead, "/objects/db/app.sqlite", nil, nil)
	expectStatus(t, head, http.StatusOK)
	if head.Header.Get("ETag") != second || head.Header.Get("Content-Length") != "2" {
		t.Fatalf("HEAD headers = %v", head.Header)
	}

	expectStatus(t, h.do(http.MethodDelete, "/objects/db/app.sqlite", nil, nil), http.StatusPreconditionRequired)
	expectStatus(t, h.do(http.MethodDelete, "/objects/db/app.sqlite", nil, map[string]string{"If-Match": first}), http.StatusPreconditionFailed)
	expectStatus(t, h.do(http.MethodDelete, "/objects/db/app.sqlite", nil, map[string]string{"If-Match": second}), http.StatusNoContent)
	expectStatus(t, h.do(http.MethodGet, "/objects/db/app.sqlite", nil, nil), http.StatusNotFound)
	expectStatus(t, h.do(http.MethodHead, "/objects/db/app.sqlite", nil, nil), http.StatusNotFound)
	expectStatus(t, h.do(http.MethodDelete, "/objects/db/app.sqlite", nil, map[string]string{"If-Match": second}), http.StatusNotFound)
	expectStatus(t, h.do(http.MethodPut, "/objects/db/app.sqlite", []byte("v3"), map[string]string{"If-Match": second}), http.StatusPreconditionFailed)
}

func TestWritesLandUnderTheInstancePrefixWithArtifactMetadata(t *testing.T) {
	h := newHarness(t)
	expectStatus(t, h.do(http.MethodPut, "/objects/notes.json", []byte(`{"a":1}`), map[string]string{"If-None-Match": "*"}), http.StatusOK)

	object, ok := h.store.objects[testPrefix+"notes.json"]
	if !ok {
		t.Fatalf("stored keys = %v", h.store.objects)
	}
	digest := sha256.Sum256([]byte(`{"a":1}`))
	if object.metadata["sha256"] != hex.EncodeToString(digest[:]) || object.checksum != base64.StdEncoding.EncodeToString(digest[:]) {
		t.Fatalf("metadata = %v checksum = %q", object.metadata, object.checksum)
	}
	if object.contentType != "application/json" {
		t.Fatalf("content type = %q, want guessed application/json", object.contentType)
	}
	expectStatus(t, h.do(http.MethodPut, "/objects/blob", []byte("x"), map[string]string{"If-None-Match": "*", "Content-Type": "application/vnd.sqlite3"}), http.StatusOK)
	if got := h.store.objects[testPrefix+"blob"].contentType; got != "application/vnd.sqlite3" {
		t.Fatalf("content type = %q, want the caller's", got)
	}
}

func TestPreconditionsMustBeExactlyOne(t *testing.T) {
	h := newHarness(t)
	expectStatus(t, h.do(http.MethodPut, "/objects/a", []byte("x"), map[string]string{"If-None-Match": "*", "If-Match": `"e"`}), http.StatusBadRequest)
	expectStatus(t, h.do(http.MethodPut, "/objects/a", []byte("x"), map[string]string{"If-None-Match": `"e"`}), http.StatusBadRequest)
}

func TestBodyOverTheLimitIsRefused(t *testing.T) {
	h := newHarness(t)
	expectStatus(t, h.do(http.MethodPut, "/objects/big", bytes.Repeat([]byte("x"), 65), map[string]string{"If-None-Match": "*"}), http.StatusRequestEntityTooLarge)
	expectStatus(t, h.do(http.MethodPut, "/objects/fits", bytes.Repeat([]byte("x"), 64), map[string]string{"If-None-Match": "*"}), http.StatusOK)
}

func TestPathsThatCouldEscapeThePrefixAreRefused(t *testing.T) {
	h := newHarness(t)
	for _, raw := range []string{
		"/objects/../inst-2/app.sqlite",
		"/objects/%2e%2e/inst-2/app.sqlite",
		"/objects/a/%2E%2E/%2E%2E/x",
		"/objects/a//b",
		"/objects/./a",
		"/objects/%2Fabs",
		"/objects/a%5Cb",
		"/objects/a%00b",
		"/objects/%ff",
		"/objects/" + strings.Repeat("a", maxPathBytes+1),
		"/objects/",
	} {
		expectStatus(t, h.do(http.MethodPut, raw, []byte("x"), map[string]string{"If-None-Match": "*"}), http.StatusBadRequest)
	}
	if len(h.store.puts) != 0 {
		t.Fatalf("a refused path reached the store: %v", aws.ToString(h.store.puts[0].Key))
	}
}

func TestListReturnsEveryPageRelativeToTheInstance(t *testing.T) {
	h := newHarness(t)
	for _, name := range []string{"a", "b/1", "b/2", "c"} {
		expectStatus(t, h.do(http.MethodPut, "/objects/"+name, []byte(name), map[string]string{"If-None-Match": "*"}), http.StatusOK)
	}
	h.store.objects["workspaces/ws-1/apps/inst-2/secret"] = storedObject{data: []byte("x"), etag: `"x"`} // pragma: allowlist secret

	var listing struct {
		Objects []listedObject `json:"objects"`
	}
	response := h.do(http.MethodGet, "/objects", nil, nil)
	expectStatus(t, response, http.StatusOK)
	if err := json.NewDecoder(response.Body).Decode(&listing); err != nil {
		t.Fatalf("decode listing: %v", err)
	}
	paths := make([]string, 0, len(listing.Objects))
	for _, object := range listing.Objects {
		paths = append(paths, object.Path)
	}
	if strings.Join(paths, ",") != "a,b/1,b/2,c" {
		t.Fatalf("listed %v", paths)
	}
	if listing.Objects[0].ETag == "" || listing.Objects[0].Size != 1 || listing.Objects[0].LastModified == "" {
		t.Fatalf("listed object = %+v", listing.Objects[0])
	}

	response = h.do(http.MethodGet, "/objects?prefix=b/", nil, nil)
	expectStatus(t, response, http.StatusOK)
	listing.Objects = nil
	_ = json.NewDecoder(response.Body).Decode(&listing)
	if len(listing.Objects) != 2 {
		t.Fatalf("prefix listing = %+v", listing.Objects)
	}
	expectStatus(t, h.do(http.MethodGet, "/objects?prefix=../inst-2", nil, nil), http.StatusBadRequest)
}

func TestTokensAreRefusedFailClosed(t *testing.T) {
	h := newHarness(t)
	expectStatus(t, h.do(http.MethodGet, "/objects", nil, map[string]string{"Authorization": ""}), http.StatusUnauthorized)
	expectStatus(t, h.do(http.MethodGet, "/objects", nil, map[string]string{"Authorization": "Bearer nonsense"}), http.StatusUnauthorized)

	other := sign(t, []byte("ffffffffffffffffffffffffffffffff"), "ws-1", "inst-1")
	expectStatus(t, h.do(http.MethodGet, "/objects", nil, map[string]string{"Authorization": "Bearer " + other}), http.StatusUnauthorized)

	expired, _ := activationauth.Sign(testSecret, activationauth.ScopeStorage, identity("ws-1", "inst-1"), activationauth.BodySHA256(nil), time.Now().Add(-2*time.Hour), time.Hour)
	expectStatus(t, h.do(http.MethodGet, "/objects", nil, map[string]string{"Authorization": "Bearer " + expired}), http.StatusUnauthorized)

	expectStatus(t, h.doAt("deleted", http.MethodGet, "/objects", nil, nil), http.StatusUnauthorized)

	moved := sign(t, testSecret, "ws-9", "inst-1")
	expectStatus(t, h.do(http.MethodGet, "/objects", nil, map[string]string{"Authorization": "Bearer " + moved}), http.StatusForbidden)

	optedOut := sign(t, testSecret, "ws-1", "inst-2")
	expectStatus(t, h.doAt("inst-2", http.MethodGet, "/objects", nil, map[string]string{"Authorization": "Bearer " + optedOut}), http.StatusForbidden)
}

func TestATokenOpensOnlyItsOwnInstancePath(t *testing.T) {
	h := newHarness(t)
	h.store.objects["workspaces/ws-1/apps/inst-3/app.sqlite"] = storedObject{data: []byte("x"), etag: `"x"`}
	expectStatus(t, h.doAt("inst-3", http.MethodGet, "/objects/app.sqlite", nil, nil), http.StatusForbidden)
	expectStatus(t, h.doAt("inst-3", http.MethodPut, "/objects/app.sqlite", []byte("y"), map[string]string{"If-Match": `"x"`}), http.StatusForbidden)
	expectStatus(t, h.doAt("..", http.MethodGet, "/objects/app.sqlite", nil, nil), http.StatusBadRequest)
	if len(h.store.puts) != 0 {
		t.Fatal("a write for another instance reached the store")
	}
}
