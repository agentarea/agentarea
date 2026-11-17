package blob

import (
	"context"
	"errors"
	"io"
	"iter"
	"strings"
	"testing"
	"time"
)

// recordStore records the keys a Scoped reaches the store with.
type recordStore struct {
	puts   []string
	copies [][2]string
	prefix string
}

func (r *recordStore) Put(_ context.Context, key string, _ io.Reader, _ int64, _ PutOptions) error {
	r.puts = append(r.puts, key)
	return nil
}
func (r *recordStore) Get(_ context.Context, key string) (io.ReadCloser, Info, error) {
	return io.NopCloser(strings.NewReader("")), Info{Key: key}, nil
}
func (r *recordStore) Stat(_ context.Context, key string) (Info, error) { return Info{Key: key}, nil }
func (r *recordStore) Delete(context.Context, string) error             { return nil }
func (r *recordStore) Copy(_ context.Context, s, d string, _ CopyOptions) error {
	r.copies = append(r.copies, [2]string{s, d})
	return nil
}
func (r *recordStore) List(_ context.Context, prefix string) iter.Seq2[Info, error] {
	r.prefix = prefix
	return func(yield func(Info, error) bool) {
		for _, k := range []string{prefix, prefix + "a.txt", prefix + "d/b.txt"} {
			if !yield(Info{Key: k}, nil) {
				return
			}
		}
	}
}
func (r *recordStore) ListDir(_ context.Context, prefix string) ([]Info, []string, error) {
	return []Info{{Key: prefix + "a.txt"}}, []string{prefix + "d/"}, nil
}
func (r *recordStore) PresignGet(_ context.Context, key string, _ time.Duration) (Presigned, error) {
	return Presigned{URL: key}, nil
}
func (r *recordStore) PresignPut(_ context.Context, key string, _ PutOptions, _ time.Duration) (Presigned, error) {
	return Presigned{URL: key}, nil
}

func TestScopedKeysStayInsideTheWorkspace(t *testing.T) {
	rs := &recordStore{}
	s, err := ForWorkspace(rs, "w1")
	if err != nil {
		t.Fatal(err)
	}
	k, err := s.Key("///a/b.txt")
	if err != nil || k != "workspaces/w1/a/b.txt" {
		t.Errorf("%q %v", k, err)
	}
	for _, bad := range []string{"", "/", "../x", "a/../b", "a/..", "a\x00b", "a\nb", "a\x7fb", strings.Repeat("a", 1020), "a\xffb"} {
		if _, err := s.Key(bad); !errors.Is(err, ErrInvalidPath) {
			t.Errorf("%q accepted: %v", bad, err)
		}
	}
	for _, ok := range []string{"a..b", "..a", "a/.hidden", "a b/ü"} {
		if _, err := s.Key(ok); err != nil {
			t.Errorf("%q refused: %v", ok, err)
		}
	}
	if _, err := ForWorkspace(rs, ""); err == nil {
		t.Error("a scope with no workspace")
	}
}

func TestScopedWriteBound(t *testing.T) {
	rs := &recordStore{}
	s, _ := ForWorkspace(rs, "w1")
	long := strings.Repeat("a", MaxWritePathBytes+1)
	if _, err := s.Key(long); err != nil {
		t.Errorf("a read of a long path: %v", err)
	}
	ctx := context.Background()
	if err := s.Put(ctx, long, strings.NewReader(""), 0, PutOptions{}); !errors.Is(err, ErrInvalidPath) {
		t.Errorf("put: %v", err)
	}
	if err := s.Copy(ctx, "a", long, CopyOptions{}); !errors.Is(err, ErrInvalidPath) {
		t.Errorf("copy: %v", err)
	}
	if _, err := s.PresignPut(ctx, long, PutOptions{}, time.Minute); !errors.Is(err, ErrInvalidPath) {
		t.Errorf("presign: %v", err)
	}
	if len(rs.puts) != 0 {
		t.Errorf("a refused write reached the store: %v", rs.puts)
	}
}

func TestScopedListIsRelativeAndSkipsTheMarker(t *testing.T) {
	rs := &recordStore{}
	s, _ := ForWorkspace(rs, "w1")
	var keys []string
	for info, err := range s.List(context.Background(), "") {
		if err != nil {
			t.Fatal(err)
		}
		keys = append(keys, info.Key)
	}
	if strings.Join(keys, ",") != "a.txt,d/b.txt" || rs.prefix != "workspaces/w1/" {
		t.Errorf("%v %q", keys, rs.prefix)
	}
	for _, err := range s.List(context.Background(), "../w2/") {
		if !errors.Is(err, ErrInvalidPath) {
			t.Errorf("a prefix that climbs: %v", err)
		}
	}
	objs, folders, _ := s.ListDir(context.Background(), "x/")
	if objs[0].Key != "x/a.txt" || folders[0] != "x/d/" {
		t.Errorf("%v %v", objs, folders)
	}
}

func TestConfig(t *testing.T) {
	c := Config{Endpoint: "http://in", PublicEndpoint: "https://out"}
	if c.Signing() != "https://out" {
		t.Error(c.Signing())
	}
	if (Config{Endpoint: "http://in"}).Signing() != "http://in" {
		t.Error("fallback")
	}
}
