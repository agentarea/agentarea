package blob

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
)

// realStore is a Store on a real S3-compatible service named by
// AGENTAREA_TEST_S3_URL (http://access:secret@host:port); skipped when unset.
func realStore(t *testing.T) (*Client, *Store) {
	t.Helper()
	raw := os.Getenv("AGENTAREA_TEST_S3_URL")
	if raw == "" {
		t.Skip("AGENTAREA_TEST_S3_URL is not set")
	}
	u, err := url.Parse(raw)
	if err != nil || u.User == nil {
		t.Fatalf("AGENTAREA_TEST_S3_URL must carry credentials: %v", err)
	}
	secret, _ := u.User.Password()
	endpoint := u.Scheme + "://" + u.Host
	bucket := "aa-go-blob-" + uuid.NewString()[:8]
	c := New(kernel.Config{Endpoint: endpoint, Region: "us-east-1", Bucket: bucket, ArtifactsBucket: bucket, AccessKey: u.User.Username(), SecretKey: secret})
	if err := c.InitBuckets(context.Background(), []string{bucket}, []string{"https://app.example.com"}); err != nil {
		t.Fatalf("init bucket: %v", err)
	}
	return c, c.Artifacts()
}

func do(t *testing.T, method, rawURL string, headers map[string]string, body []byte) (*http.Response, []byte) {
	t.Helper()
	req, _ := http.NewRequest(method, rawURL, bytes.NewReader(body))
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	out, _ := io.ReadAll(resp.Body)
	return resp, out
}

var trickyKeys = []string{
	"workspaces/w/plain.txt",
	"workspaces/w/with space.txt",
	"workspaces/w/plus+colon:at@amp&eq=.txt",
	"workspaces/w/ü/ключ/日本語.md",
	"workspaces/w/(paren)[brk]!~'*.bin",
}

func TestRealStoreRoundTripAndPresigned(t *testing.T) {
	_, st := realStore(t)
	ctx := context.Background()
	for _, key := range trickyKeys {
		body := make([]byte, 5000)
		_, _ = rand.Read(body)
		sum := digest(body)
		if err := st.Put(ctx, key, bytes.NewReader(body), int64(len(body)), kernel.PutOptions{ContentType: "application/x-test", Metadata: map[string]string{"sha256": sum}, SHA256: sum}); err != nil {
			t.Fatalf("put %q: %v", key, err)
		}
		stat, err := st.Stat(ctx, key)
		if err != nil || stat.SHA256 != sum || stat.Size != 5000 || stat.ContentType != "application/x-test" {
			t.Fatalf("stat %q: %+v %v", key, stat, err)
		}
		rc, _, err := st.Get(ctx, key)
		if err != nil {
			t.Fatal(err)
		}
		got, _ := io.ReadAll(rc)
		_ = rc.Close()
		if !bytes.Equal(got, body) {
			t.Errorf("%q: body differs", key)
		}

		p, err := st.PresignGet(ctx, key, time.Hour)
		if err != nil {
			t.Fatal(err)
		}
		resp, data := do(t, http.MethodGet, p.URL, nil, nil)
		if resp.StatusCode != 200 || !bytes.Equal(data, body) {
			t.Errorf("presigned GET %q: %d %s", key, resp.StatusCode, data[:min(len(data), 200)])
		}
	}
}

func TestRealPresignedPutIsContentVerified(t *testing.T) {
	_, st := realStore(t)
	ctx := context.Background()
	for _, key := range trickyKeys {
		body := []byte("uploaded straight from a browser: " + key)
		sum := digest(body)
		p, err := st.PresignPut(ctx, key, kernel.PutOptions{ContentType: "text/plain", SHA256: sum, Metadata: map[string]string{"sha256": sum}}, 10*time.Minute)
		if err != nil {
			t.Fatal(err)
		}
		if resp, out := do(t, http.MethodPut, p.URL, p.Headers, body); resp.StatusCode != 200 {
			t.Fatalf("presigned PUT %q: %d %s", key, resp.StatusCode, out)
		}
		stat, err := st.Stat(ctx, key)
		if err != nil || stat.SHA256 != sum || stat.ContentType != "text/plain" || stat.Metadata["sha256"] != sum {
			t.Errorf("after upload %q: %+v %v", key, stat, err)
		}
	}

	key := "workspaces/w/verified.bin"
	body := []byte("the declared bytes")
	sum := digest(body)
	p, _ := st.PresignPut(ctx, key, kernel.PutOptions{ContentType: "text/plain", SHA256: sum, Metadata: map[string]string{"sha256": sum}}, time.Minute)
	if resp, _ := do(t, http.MethodPut, p.URL, p.Headers, []byte("other bytes")); resp.StatusCode == 200 {
		t.Error("the store accepted a body that does not hash to the signed digest")
	}
	noHeaders := map[string]string{}
	if resp, _ := do(t, http.MethodPut, p.URL, noHeaders, body); resp.StatusCode == 200 {
		t.Error("the store accepted an upload without the signed headers")
	}
	tampered := map[string]string{}
	for k, v := range p.Headers {
		tampered[k] = v
	}
	tampered["Content-Type"] = "text/html"
	if resp, _ := do(t, http.MethodPut, p.URL, tampered, body); resp.StatusCode == 200 {
		t.Error("the store accepted a changed Content-Type")
	}
}

func TestRealConditionalPutAndCopyAndList(t *testing.T) {
	_, st := realStore(t)
	ctx := context.Background()
	put := func(key, body string, o kernel.PutOptions) error {
		return st.Put(ctx, key, strings.NewReader(body), int64(len(body)), o)
	}
	if err := put("ws/current.json", "{}", kernel.PutOptions{IfNoneMatch: true}); err != nil {
		t.Fatal(err)
	}
	if err := put("ws/current.json", "{1}", kernel.PutOptions{IfNoneMatch: true}); !errors.Is(err, kernel.ErrPreconditionFailed) {
		t.Errorf("create over existing: %v", err)
	}
	stat, _ := st.Stat(ctx, "ws/current.json")
	if err := put("ws/current.json", "{2}", kernel.PutOptions{IfMatch: stat.ETag}); err != nil {
		t.Errorf("cas: %v", err)
	}
	if err := put("ws/current.json", "{3}", kernel.PutOptions{IfMatch: stat.ETag}); !errors.Is(err, kernel.ErrPreconditionFailed) {
		t.Errorf("stale cas: %v", err)
	}

	sum := digest([]byte("copy me"))
	if err := put("ws/src dir/a+b.txt", "copy me", kernel.PutOptions{ContentType: "text/plain", Metadata: map[string]string{"sha256": sum}}); err != nil {
		t.Fatal(err)
	}
	if err := st.Copy(ctx, "ws/src dir/a+b.txt", "ws/dst/ü.txt", kernel.CopyOptions{}); err != nil {
		t.Fatal(err)
	}
	if s, err := st.Stat(ctx, "ws/dst/ü.txt"); err != nil || s.Metadata["sha256"] != sum || s.ContentType != "text/plain" {
		t.Errorf("copy lost metadata: %+v %v", s, err)
	}
	if err := st.Copy(ctx, "ws/dst/ü.txt", "ws/dst/r.txt", kernel.CopyOptions{Replace: true, ContentType: "text/csv", Metadata: map[string]string{"sha256": "new"}}); err != nil {
		t.Fatal(err)
	}
	if s, _ := st.Stat(ctx, "ws/dst/r.txt"); s.Metadata["sha256"] != "new" || s.ContentType != "text/csv" {
		t.Errorf("replace: %+v", s)
	}

	objects, folders, err := st.ListDir(ctx, "ws/")
	if err != nil {
		t.Fatal(err)
	}
	if len(objects) != 1 || objects[0].Key != "ws/current.json" || strings.Join(folders, ",") != "ws/dst/,ws/src dir/" {
		t.Errorf("listdir: %v %v", objects, folders)
	}
	var n int
	for _, err := range st.List(ctx, "ws/") {
		if err != nil {
			t.Fatal(err)
		}
		n++
	}
	if n != 4 {
		t.Errorf("list: %d", n)
	}
	if err := st.Delete(ctx, "ws/dst/r.txt"); err != nil {
		t.Fatal(err)
	}
	if _, err := st.Stat(ctx, "ws/dst/r.txt"); !errors.Is(err, kernel.ErrNotFound) {
		t.Errorf("after delete: %v", err)
	}
}

func TestRealListPaginates(t *testing.T) {
	_, st := realStore(t)
	ctx := context.Background()
	const n = 1100
	for i := 0; i < n; i++ {
		if err := st.Put(ctx, "many/"+strings.Repeat("0", 4-len(itoa(i)))+itoa(i), strings.NewReader("x"), 1, kernel.PutOptions{}); err != nil {
			t.Fatal(err)
		}
	}
	count, last := 0, ""
	for info, err := range st.List(ctx, "many/") {
		if err != nil {
			t.Fatal(err)
		}
		if info.Key <= last {
			t.Fatalf("not in key order: %s after %s", info.Key, last)
		}
		last = info.Key
		count++
	}
	if count != n {
		t.Errorf("listed %d of %d", count, n)
	}
}

func itoa(i int) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	var b []byte
	for ; i > 0; i /= 10 {
		b = append([]byte{digits[i%10]}, b...)
	}
	return string(b)
}

// TestPresignMatchesBoto3 signs the same upload with the Python code's
// boto3 client (offline, no request) and compares what the signature binds.
func TestPresignMatchesBoto3(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv is not installed")
	}
	dir, _ := filepath.Abs("../../../../../agentarea-platform")
	if _, err := os.Stat(filepath.Join(dir, "libs", "common")); err != nil {
		t.Skip("agentarea-platform is not checked out next to agentarea-go")
	}
	sum := digest([]byte("x"))
	raw, _ := hex.DecodeString(sum)
	sumB64 := base64.StdEncoding.EncodeToString(raw)
	script := `
import boto3, sys, json
from botocore.client import Config
c = boto3.client("s3", aws_access_key_id="AKID", aws_secret_access_key="SECRET", region_name="us-east-1",
                 endpoint_url="https://files.example.com", config=Config(signature_version="s3v4"))
put = c.generate_presigned_url("put_object", Params={"Bucket": "artifacts", "Key": "workspaces/w/a b+c.txt", "ContentType": "text/plain",
    "ChecksumSHA256": sys.argv[1], "Metadata": {"sha256": sys.argv[2]}}, ExpiresIn=600)
get = c.generate_presigned_url("get_object", Params={"Bucket": "artifacts", "Key": "workspaces/w/a b+c.txt"}, ExpiresIn=3600)
print(json.dumps({"put": put, "get": get}))
`
	cmd := exec.Command("uv", "run", "python", "-c", script, sumB64, sum)
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("python: %v", err)
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	var py struct{ Put, Get string }
	if err := jsonUnmarshal([]byte(lines[len(lines)-1]), &py); err != nil {
		t.Fatal(err)
	}
	c := New(kernel.Config{Endpoint: "http://rustfs:9000", PublicEndpoint: "https://files.example.com", Region: "us-east-1", ArtifactsBucket: "artifacts", AccessKey: "AKID", SecretKey: "SECRET"})
	st := c.Artifacts()
	goPut, err := st.PresignPut(context.Background(), "workspaces/w/a b+c.txt", kernel.PutOptions{ContentType: "text/plain", SHA256: sum, Metadata: map[string]string{"sha256": sum}}, 10*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	goGet, _ := st.PresignGet(context.Background(), "workspaces/w/a b+c.txt", time.Hour)

	for name, pair := range map[string][2]string{"put": {py.Put, goPut.URL}, "get": {py.Get, goGet.URL}} {
		a, _ := url.Parse(pair[0])
		b, _ := url.Parse(pair[1])
		if a.Host != b.Host || a.EscapedPath() != b.EscapedPath() {
			t.Errorf("%s: python %s%s, go %s%s", name, a.Host, a.EscapedPath(), b.Host, b.EscapedPath())
		}
		for _, k := range []string{"X-Amz-Expires", "X-Amz-Algorithm", "X-Amz-SignedHeaders"} {
			if a.Query().Get(k) != b.Query().Get(k) {
				t.Errorf("%s %s: python %q, go %q", name, k, a.Query().Get(k), b.Query().Get(k))
			}
		}
		for k := range a.Query() {
			if b.Query().Get(k) == "" && k != "X-Amz-Security-Token" {
				t.Errorf("%s: python carries query %s, go does not", name, k)
			}
		}
	}
}
