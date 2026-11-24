package handlers

import (
	"bytes"
	"context"
	"io"
	"iter"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/schema"
)

type skillGraph struct {
	mu   sync.Mutex
	objs map[string]bool
}

func (g *skillGraph) Check(_ context.Context, _, _, _, id string) (bool, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.objs[id], nil
}

func (g *skillGraph) ListObjects(context.Context, string, string, string) ([]string, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	var out []string
	for id := range g.objs {
		out = append(out, id)
	}
	return out, nil
}

func (g *skillGraph) Write(_ context.Context, writes, _ []authz.Tuple) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	for _, w := range writes {
		if id, ok := strings.CutPrefix(w.Object, authz.TypeResource+":"); ok {
			g.objs[id] = true
		}
	}
	return nil
}

type skillBlob struct {
	blob.Store
	mu   sync.Mutex
	objs map[string][]byte
}

func (b *skillBlob) Put(_ context.Context, key string, body io.Reader, _ int64, _ blob.PutOptions) error {
	d, err := io.ReadAll(body)
	b.mu.Lock()
	b.objs[key] = d
	b.mu.Unlock()
	return err
}

func (b *skillBlob) Get(_ context.Context, key string) (io.ReadCloser, blob.Info, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	d, ok := b.objs[key]
	if !ok {
		return nil, blob.Info{}, blob.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(d)), blob.Info{Key: key, Size: int64(len(d))}, nil
}

func (b *skillBlob) List(_ context.Context, prefix string) iter.Seq2[blob.Info, error] {
	return func(yield func(blob.Info, error) bool) {
		b.mu.Lock()
		var infos []blob.Info
		for k, d := range b.objs {
			if strings.HasPrefix(k, prefix) {
				infos = append(infos, blob.Info{Key: k, Size: int64(len(d))})
			}
		}
		b.mu.Unlock()
		for _, i := range infos {
			if !yield(i, nil) {
				return
			}
		}
	}
}

func (b *skillBlob) PresignGet(_ context.Context, key string, _ time.Duration) (blob.Presigned, error) {
	return blob.Presigned{URL: "https://s3.test/" + key}, nil
}

func skillDB(t *testing.T) db.Database {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_DB_TEST_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_DB_TEST_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	u, _ := url.Parse(dsn)
	port, _ := strconv.Atoi(u.Port())
	pass, _ := u.User.Password()
	pools, err := db.Open(context.Background(), db.Config{
		Host: u.Hostname(), Port: port, Name: strings.TrimPrefix(u.Path, "/"), User: u.User.Username(), Password: pass,
		SSLMode: u.Query().Get("sslmode"), PoolSize: 4, PoolTimeout: 10 * time.Second,
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pools.Close)
	return pools
}

func skillServer(t *testing.T) (http.Handler, string) {
	t.Helper()
	d := skillDB(t)
	svc := service.New(service.Deps{DB: d, Graph: &skillGraph{objs: map[string]bool{}}})
	slug := "ws-" + uuid.NewString()[:8]
	ws, err := scope.NewWorkspace(uuid.NewString(), slug)
	if err != nil {
		t.Fatal(err)
	}
	edge := Edge{Workspace: func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: ws}
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), c)))
		})
	}}
	r := chi.NewRouter()
	k := service.NewSkills(svc, service.SkillPorts{Blob: &skillBlob{objs: map[string][]byte{}}})
	Mount(r, httpx.NewErrors("", nil, MapError), edge, New(svc, Extras{Skills: k}))
	return r, "/v1/workspaces/" + slug + "/skills"
}

func skillDo(h http.Handler, method, path, ct string, body []byte) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	r := httptest.NewRequest(method, path, bytes.NewReader(body))
	if ct != "" {
		r.Header.Set("Content-Type", ct)
	}
	h.ServeHTTP(rec, r)
	return rec
}

func skillUpload(t *testing.T, filename string, files map[string]string) (string, []byte) {
	t.Helper()
	var fs domain.SkillFiles
	for p, d := range files {
		fs.Set(p, []byte(d))
	}
	z, err := domain.SkillZip(fs)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	fw, _ := mw.CreateFormFile("file", filename)
	_, _ = fw.Write(z)
	_ = mw.Close()
	return mw.FormDataContentType(), buf.Bytes()
}

func TestSkillRoutes(t *testing.T) {
	h, p := skillServer(t)
	rec := skillDo(h, "POST", p, "application/json", []byte(`{"content":"---\nname: PDF\n---\n# PDF"}`))
	if rec.Code != 200 || !strings.HasPrefix(rec.Body.String(), `{"id":"`) || !strings.Contains(rec.Body.String(), `"slug":"pdf","description":null,"source_type":"content"`) ||
		!strings.Contains(rec.Body.String(), `"customized":false,"registry_name":null`) {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	id := strings.SplitN(strings.TrimPrefix(rec.Body.String(), `{"id":"`), `"`, 2)[0]

	ct, body := skillUpload(t, "pkg.ZIP", map[string]string{"SKILL.md": "# Zipped", "ref/deep/a.txt": "a"})
	rec = skillDo(h, "POST", p+"/upload?name=Up", ct, body)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"name":"Up"`) || !strings.Contains(rec.Body.String(), `"source_type":"zip"`) {
		t.Fatalf("upload %d %s", rec.Code, rec.Body)
	}
	up := strings.SplitN(strings.TrimPrefix(rec.Body.String(), `{"id":"`), `"`, 2)[0]

	rec = skillDo(h, "GET", p+"/"+up+"/files/ref/deep/a.txt?redirect=false", "", nil)
	if rec.Code != 200 || !strings.HasSuffix(strings.TrimSpace(rec.Body.String()), `/ref/deep/a.txt"}`) {
		t.Fatalf("file url %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "GET", p+"/"+up+"/files/ref/deep/a.txt", "", nil)
	if rec.Code != http.StatusTemporaryRedirect || !strings.HasPrefix(rec.Header().Get("Location"), "https://s3.test/skills/") {
		t.Fatalf("redirect %d %v", rec.Code, rec.Header())
	}
	rec = skillDo(h, "GET", p+"/"+up+"/files?include_urls=true", "", nil)
	if rec.Code != 200 || !strings.HasPrefix(rec.Body.String(), `{"skill_id":"`+up+`","files":[`) || strings.Count(rec.Body.String(), `"url":"https://`) != 2 {
		t.Fatalf("files %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "GET", p+"/"+id+"/content", "", nil)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"content":"---\nname: PDF\n---\n# PDF"`) {
		t.Fatalf("content %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "GET", p+"?page_size=1", "", nil)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"total":2,"page":1,"page_size":1,"has_next":true`) {
		t.Fatalf("list %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "POST", p+"/"+id+"/members", "application/json", []byte(`{"child_skill_id":"`+up+`","order":"2"}`))
	if rec.Code != 200 || rec.Body.String() != `{"parent_skill_id":"`+id+`","child_skill_id":"`+up+`","order":2,"is_required":true,"dependencies":[]}` {
		t.Fatalf("member %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "GET", p+"/"+id+"/flatten", "", nil)
	if rec.Code != 200 || rec.Body.String() != `["`+up+`"]` {
		t.Fatalf("flatten %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "GET", p+"/"+id+"/versions", "", nil)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"reason":"create","catalog_version":null,"created_by":"u"`) || !strings.Contains(rec.Body.String(), `"current":true}]`) {
		t.Fatalf("versions %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "DELETE", p+"/"+id, "", nil)
	if rec.Code != 200 || rec.Body.String() != `{"status":"deleted","id":"`+id+`"}` {
		t.Fatalf("delete %d %s", rec.Code, rec.Body)
	}
	rec = skillDo(h, "GET", p+"/"+id, "", nil)
	if rec.Code != 403 && rec.Code != 404 {
		t.Fatalf("after delete %d %s", rec.Code, rec.Body)
	}
}

func TestSkillRouteValidation(t *testing.T) {
	h, p := skillServer(t)
	for _, tc := range []struct {
		method, path, ct, body string
		code                   int
		want                   string
	}{
		{"POST", p, "application/json", `{}`, 422, `Value error, Either 'content' or 'github_url' must be provided`},
		{"POST", p, "application/json", `{"content":"x","github_url":"y"}`, 422, `Only one of 'content' or 'github_url' can be provided`},
		{"POST", p, "application/json", `{"content":"---\na: &x 1\nb: *x\n---\n"}`, 422, `SKILL.md frontmatter is refused`},
		{"POST", p + "/upload", "application/json", `{}`, 422, `"loc":["body","file"]`},
		{"GET", p + "?from_registry=maybe", "", "", 422, `"bool_parsing"`},
		{"GET", p + "/not-a-uuid", "", "", 422, `"uuid_parsing"`},
		{"POST", p + "/" + uuid.NewString() + "/members", "application/json", `{"order":2147483648}`, 422, `"less_than_equal"`},
	} {
		rec := skillDo(h, tc.method, tc.path, tc.ct, []byte(tc.body))
		if rec.Code != tc.code || !strings.Contains(rec.Body.String(), tc.want) {
			t.Errorf("%s %s %s: %d %s", tc.method, tc.path, tc.body, rec.Code, rec.Body)
		}
	}
	ct, body := skillUpload(t, "pkg.tar", map[string]string{"SKILL.md": "x"})
	if rec := skillDo(h, "POST", p+"/upload", ct, body); rec.Code != 400 || !strings.Contains(rec.Body.String(), "File must be a ZIP archive") {
		t.Errorf("not zip: %d %s", rec.Code, rec.Body)
	}
	ct, body = skillUpload(t, "pkg.zip", map[string]string{"a.txt": "x"})
	if rec := skillDo(h, "POST", p+"/upload", ct, body); rec.Code != 400 {
		t.Errorf("no SKILL.md: %d %s", rec.Code, rec.Body)
	}
	var big bytes.Buffer
	mw := multipart.NewWriter(&big)
	fw, _ := mw.CreateFormFile("file", "big.zip")
	_, _ = fw.Write(make([]byte, domain.SkillMaxPackageTotalBytes+1))
	_ = mw.Close()
	if rec := skillDo(h, "POST", p+"/upload", mw.FormDataContentType(), big.Bytes()); rec.Code != 400 ||
		!strings.Contains(rec.Body.String(), "Skill package is larger than 50 MB uncompressed") {
		t.Errorf("oversized upload: %d %s", rec.Code, rec.Body)
	}
	if rec := skillDo(h, "POST", p+"/update-all", "", nil); rec.Code != 501 {
		t.Errorf("update-all without the catalog: %d %s", rec.Code, rec.Body)
	}
}
