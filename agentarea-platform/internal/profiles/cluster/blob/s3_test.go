package blob

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"net/url"
	"slices"
	"strings"
	"testing"
	"time"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
)

func testClient(endpoint, public string) *Client {
	return New(kernel.Config{Endpoint: endpoint, PublicEndpoint: public, Region: "us-east-1", Bucket: "b", ArtifactsBucket: "artifacts", AccessKey: "AKID", SecretKey: "SECRET"})
}

func digest(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

func TestPublicHostIsWherePresignedURLsGo(t *testing.T) {
	for _, c := range []struct {
		cfg  kernel.Config
		want string
	}{
		{kernel.Config{Endpoint: "http://rustfs:9000", PublicEndpoint: "https://storage.example.com", ArtifactsBucket: "artifacts"}, "storage.example.com"},
		{kernel.Config{Endpoint: "http://localhost:9000", ArtifactsBucket: "artifacts"}, "localhost"},
		{kernel.Config{Region: "eu-west-1", ArtifactsBucket: "artifacts"}, "artifacts.s3.eu-west-1.amazonaws.com"},
		{kernel.Config{Region: "us-east-1", ArtifactsBucket: "artifacts"}, "artifacts.s3.amazonaws.com"},
	} {
		if got := New(c.cfg).PublicHost(); got != c.want {
			t.Errorf("%+v: %q, want %q", c.cfg, got, c.want)
		}
	}
}

func TestPutGetStatRoundTrip(t *testing.T) {
	fake, srv := newFakeS3(t, "artifacts")
	st := testClient(srv.URL, "").Artifacts()
	ctx := context.Background()
	body := []byte("hello world")
	sum := digest(body)

	if err := st.Put(ctx, "workspaces/w/a b/ü.txt", bytes.NewReader(body), int64(len(body)), kernel.PutOptions{
		ContentType: "text/plain", Metadata: map[string]string{"sha256": sum}, SHA256: sum,
	}); err != nil {
		t.Fatal(err)
	}
	req := fake.last()
	if req.Header.Get("x-amz-meta-sha256") != sum || req.Header.Get("Content-Type") != "text/plain" {
		t.Errorf("headers: %v", req.Header)
	}
	raw, _ := hex.DecodeString(sum)
	if req.Header.Get("x-amz-checksum-sha256") != base64.StdEncoding.EncodeToString(raw) {
		t.Errorf("checksum header %q", req.Header.Get("x-amz-checksum-sha256"))
	}

	rc, info, err := st.Get(ctx, "workspaces/w/a b/ü.txt")
	if err != nil {
		t.Fatal(err)
	}
	got, _ := io.ReadAll(rc)
	_ = rc.Close()
	if !bytes.Equal(got, body) || info.ContentType != "text/plain" || info.Size != int64(len(body)) || info.SHA256 != sum || strings.Contains(info.ETag, `"`) {
		t.Errorf("%q %+v", got, info)
	}
	stat, err := st.Stat(ctx, "workspaces/w/a b/ü.txt")
	if err != nil || stat.SHA256 != sum || stat.Metadata["sha256"] != sum {
		t.Errorf("%+v %v", stat, err)
	}
	if fake.last().Header.Get("x-amz-checksum-mode") != "ENABLED" {
		t.Error("Stat must ask for checksums")
	}
}

func TestStatDerivesDigestFromNativeChecksum(t *testing.T) {
	_, srv := newFakeS3(t, "artifacts")
	st := testClient(srv.URL, "").Artifacts()
	ctx := context.Background()
	body := []byte("direct upload")
	// A presigned upload carries the native checksum and no user metadata.
	if err := st.Put(ctx, "k", bytes.NewReader(body), -1, kernel.PutOptions{SHA256: digest(body)}); err != nil {
		t.Fatal(err)
	}
	stat, err := st.Stat(ctx, "k")
	if err != nil || stat.SHA256 != digest(body) {
		t.Errorf("%+v %v", stat, err)
	}
	if _, info, _ := st.Get(ctx, "k"); info.SHA256 != "" {
		t.Errorf("Get only knows the metadata digest: %q", info.SHA256)
	}
	if err := st.Put(ctx, "plain", strings.NewReader("x"), 1, kernel.PutOptions{}); err != nil {
		t.Fatal(err)
	}
	if s, _ := st.Stat(ctx, "plain"); s.SHA256 != "" {
		t.Errorf("no digest to know: %q", s.SHA256)
	}
	if err := st.Put(ctx, "bad", strings.NewReader("x"), 1, kernel.PutOptions{SHA256: "XYZ"}); err == nil {
		t.Error("accepted a malformed digest")
	}
}

func TestNotFoundAndDelete(t *testing.T) {
	_, srv := newFakeS3(t, "artifacts")
	st := testClient(srv.URL, "").Artifacts()
	ctx := context.Background()
	if _, _, err := st.Get(ctx, "nope"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("get: %v", err)
	}
	if _, err := st.Stat(ctx, "nope"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("stat: %v", err)
	}
	if err := st.Delete(ctx, "nope"); err != nil {
		t.Errorf("delete of a missing key: %v", err)
	}
}

func TestConditionalPuts(t *testing.T) {
	_, srv := newFakeS3(t, "artifacts")
	st := testClient(srv.URL, "").Artifacts()
	ctx := context.Background()
	put := func(body string, o kernel.PutOptions) error {
		return st.Put(ctx, "current.json", strings.NewReader(body), int64(len(body)), o)
	}
	if err := put("v1", kernel.PutOptions{IfNoneMatch: true}); err != nil {
		t.Fatal(err)
	}
	if err := put("v1b", kernel.PutOptions{IfNoneMatch: true}); !errors.Is(err, kernel.ErrPreconditionFailed) {
		t.Errorf("create over existing: %v", err)
	}
	stat, _ := st.Stat(ctx, "current.json")
	if err := put("v2", kernel.PutOptions{IfMatch: stat.ETag}); err != nil {
		t.Fatalf("cas with current etag: %v", err)
	}
	if err := put("v3", kernel.PutOptions{IfMatch: stat.ETag}); !errors.Is(err, kernel.ErrPreconditionFailed) {
		t.Errorf("cas with stale etag: %v", err)
	}
}

func TestCopyKeepsOrReplacesMetadata(t *testing.T) {
	fake, srv := newFakeS3(t, "artifacts")
	st := testClient(srv.URL, "").Artifacts()
	ctx := context.Background()
	if err := st.Put(ctx, "dir/a b+c.txt", strings.NewReader("x"), 1, kernel.PutOptions{ContentType: "text/plain", Metadata: map[string]string{"sha256": digest([]byte("x"))}}); err != nil {
		t.Fatal(err)
	}
	if err := st.Copy(ctx, "dir/a b+c.txt", "moved/ü.txt", kernel.CopyOptions{}); err != nil {
		t.Fatal(err)
	}
	if dir := fake.last().Header.Get("x-amz-metadata-directive"); dir != "" && dir != "COPY" {
		t.Errorf("directive %q", dir)
	}
	if s, err := st.Stat(ctx, "moved/ü.txt"); err != nil || s.Metadata["sha256"] == "" {
		t.Errorf("metadata lost on copy: %+v %v", s, err)
	}
	if err := st.Copy(ctx, "dir/a b+c.txt", "r.bin", kernel.CopyOptions{Replace: true, ContentType: "application/x", Metadata: map[string]string{"sha256": "new"}}); err != nil {
		t.Fatal(err)
	}
	if s, _ := st.Stat(ctx, "r.bin"); s.Metadata["sha256"] != "new" || s.ContentType != "application/x" {
		t.Errorf("%+v", s)
	}
	if err := st.Copy(ctx, "missing", "x", kernel.CopyOptions{}); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("copy of a missing source: %v", err)
	}
}

func TestListPaginatesAndDelimits(t *testing.T) {
	fake, srv := newFakeS3(t, "artifacts")
	fake.pageSize = 2
	st := testClient(srv.URL, "").Artifacts()
	ctx := context.Background()
	for _, k := range []string{"ws/a.txt", "ws/b.txt", "ws/c.txt", "ws/tasks/t1/x", "ws/tasks/t2/y", "ws/docs/d.md", "other/z"} {
		if err := st.Put(ctx, k, strings.NewReader("1"), 1, kernel.PutOptions{}); err != nil {
			t.Fatal(err)
		}
	}
	var keys []string
	for info, err := range st.List(ctx, "ws/") {
		if err != nil {
			t.Fatal(err)
		}
		keys = append(keys, info.Key)
	}
	want := []string{"ws/a.txt", "ws/b.txt", "ws/c.txt", "ws/docs/d.md", "ws/tasks/t1/x", "ws/tasks/t2/y"}
	if !slices.Equal(keys, want) {
		t.Errorf("list: %v", keys)
	}
	objects, folders, err := st.ListDir(ctx, "ws/")
	if err != nil {
		t.Fatal(err)
	}
	var onames []string
	for _, o := range objects {
		onames = append(onames, o.Key)
	}
	if !slices.Equal(onames, []string{"ws/a.txt", "ws/b.txt", "ws/c.txt"}) || !slices.Equal(folders, []string{"ws/docs/", "ws/tasks/"}) {
		t.Errorf("listdir: %v %v", onames, folders)
	}
	n := 0
	for _, err := range st.List(ctx, "ws/") {
		if err != nil {
			t.Fatal(err)
		}
		n++
		break
	}
	if n != 1 {
		t.Error("early stop")
	}
}

func TestPresignGetSignsAgainstThePublicEndpoint(t *testing.T) {
	c := testClient("http://rustfs:9000", "https://files.example.com")
	p, err := c.Artifacts().PresignGet(context.Background(), "workspaces/w/a b.txt", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(p.URL)
	if u.Scheme != "https" || u.Host != "files.example.com" || u.Path != "/artifacts/workspaces/w/a b.txt" {
		t.Errorf("url %s", p.URL)
	}
	q := u.Query()
	if q.Get("X-Amz-Expires") != "3600" || q.Get("X-Amz-Algorithm") != "AWS4-HMAC-SHA256" || q.Get("X-Amz-Signature") == "" {
		t.Errorf("query %v", q)
	}
	if !strings.HasPrefix(q.Get("X-Amz-Credential"), "AKID/") || q.Get("X-Amz-SignedHeaders") != "host" {
		t.Errorf("query %v", q)
	}
	if strings.Contains(p.URL, "response-content") {
		t.Error("a GET signature carries no response overrides")
	}
	if len(p.Headers) != 0 || p.TTL != time.Hour {
		t.Errorf("%+v", p)
	}
}

func TestPresignFallsBackToInternalEndpoint(t *testing.T) {
	c := testClient("http://rustfs:9000", "")
	p, _ := c.Artifacts().PresignGet(context.Background(), "k", time.Minute)
	if u, _ := url.Parse(p.URL); u.Host != "rustfs:9000" {
		t.Errorf("%s", p.URL)
	}
}

func TestPresignPutBindsDigestMetadataAndContentType(t *testing.T) {
	c := testClient("http://rustfs:9000", "https://files.example.com")
	sum := digest([]byte("body"))
	p, err := c.Artifacts().PresignPut(context.Background(), "workspaces/w/f.bin", kernel.PutOptions{
		ContentType: "application/octet-stream", SHA256: sum, Metadata: map[string]string{"sha256": sum},
	}, 10*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(p.URL)
	q := u.Query()
	if q.Get("X-Amz-Expires") != "600" {
		t.Errorf("expires %q", q.Get("X-Amz-Expires"))
	}
	signed := strings.Split(q.Get("X-Amz-SignedHeaders"), ";")
	for _, h := range []string{"host", "content-type", "x-amz-checksum-sha256", "x-amz-meta-sha256"} {
		if !slices.Contains(signed, h) {
			t.Errorf("%s is not signed: %v", h, signed)
		}
	}
	raw, _ := hex.DecodeString(sum)
	if p.Headers["Content-Type"] != "application/octet-stream" || p.Headers["x-amz-meta-sha256"] != sum ||
		p.Headers["x-amz-checksum-sha256"] != base64.StdEncoding.EncodeToString(raw) {
		t.Errorf("headers the uploader must send: %v", p.Headers)
	}
	if _, ok := p.Headers["Host"]; ok {
		t.Error("Host is not a header the uploader sets")
	}
	if _, err := c.Artifacts().PresignPut(context.Background(), "k", kernel.PutOptions{SHA256: "bad"}, time.Minute); err == nil {
		t.Error("accepted a malformed digest")
	}
}

func TestInitBucketsRefusesWildcardOrigin(t *testing.T) {
	c := testClient("http://127.0.0.1:1", "")
	if err := c.InitBuckets(context.Background(), []string{"a"}, []string{"*"}); err == nil {
		t.Error("wildcard CORS accepted")
	}
}
