package store

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestKratosDirectory(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.EscapedPath() {
		case "/admin/identities/named":
			_, _ = w.Write([]byte(`{"traits":{"email":"n@x.co","name":{"first":"Ann","last":"Lee"}}}`))
		case "/admin/identities/plain":
			_, _ = w.Write([]byte(`{"traits":{"email":"p@x.co","username":"  pat "}}`))
		case "/admin/identities/a%2Fb":
			_, _ = w.Write([]byte(`{"traits":{"name":" Solo "}}`))
		case "/admin/identities/broken":
			w.WriteHeader(http.StatusInternalServerError)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()
	if _, err := NewKratos("  ", nil, nil); err == nil {
		t.Fatal("blank admin url accepted")
	}
	k, err := NewKratos(srv.URL+"/", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	got, err := k.Resolve(context.Background(), []string{"named", "plain", "a/b", "missing", "broken", "named", ""})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Fatalf("resolved %v", got)
	}
	if n := got["named"]; *n.DisplayName != "Ann Lee" || *n.Email != "n@x.co" {
		t.Fatalf("named %+v", n)
	}
	if p := got["plain"]; *p.DisplayName != "pat" {
		t.Fatalf("plain %+v", p)
	}
	if s := got["a/b"]; *s.DisplayName != "Solo" || s.Email != nil {
		t.Fatalf("quoted %+v", s)
	}
	if rec, err := k.Lookup(context.Background(), "missing"); rec != nil || err != nil {
		t.Fatalf("missing %v %v", rec, err)
	}
	if _, err := k.Lookup(context.Background(), "broken"); !errors.Is(err, ErrDirectoryUnavailable) {
		t.Fatalf("broken %v", err)
	}
}

type kv struct{ key, value string }

func (k *kv) SetEX(_ context.Context, key, value string, ttl time.Duration) error {
	if ttl != 600*time.Second {
		return errors.New("ttl")
	}
	k.key, k.value = key, value
	return nil
}

func TestLinkCodesStoreOnlyADigest(t *testing.T) {
	store := &kv{}
	code, err := LinkCodes{KV: store}.Issue(context.Background(), "user")
	if err != nil {
		t.Fatal(err)
	}
	if len(code) != 32 || store.value != "user" || !strings.HasPrefix(store.key, LinkCodePrefix+":") || strings.Contains(store.key, code) {
		t.Fatalf("code %q stored %+v", code, store)
	}
}
