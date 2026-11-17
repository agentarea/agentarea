package netguard

import (
	"context"
	"encoding/json"
	"errors"
	"net/netip"
	"os"
	"testing"
)

type golden struct {
	Blocked map[string]bool `json:"blocked"`
	Permits [][4]any        `json:"permits"`
}

func loadGolden(t *testing.T) golden {
	t.Helper()
	raw, err := os.ReadFile("testdata/policy.json")
	if err != nil {
		t.Fatal(err)
	}
	var g golden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	return g
}

func TestBlockedMatchesPython(t *testing.T) {
	for addr, want := range loadGolden(t).Blocked {
		if _, got := Blocked(netip.MustParseAddr(addr)); got != want {
			t.Errorf("Blocked(%s) = %v, Python %v", addr, got, want)
		}
	}
}

func TestPermitsMatchesPython(t *testing.T) {
	policies := map[string]*AddressPolicy{}
	for name, args := range map[string]struct {
		allow bool
		list  []string
	}{
		"closed":        {},
		"allow_private": {allow: true},
		"allowlist": {list: []string{"localhost", "*.svc.cluster.local", "Ollama.LAN", "192.168.1.0/24",
			"10.1.2.3/8", "fd00::/8", "host-[0-9]"}},
	} {
		p, err := NewAddressPolicy(args.allow, args.list)
		if err != nil {
			t.Fatal(err)
		}
		policies[name] = p
	}
	g := loadGolden(t)
	if len(g.Permits) == 0 {
		t.Fatal("no permits cases")
	}
	for _, c := range g.Permits {
		name, host, addr, want := c[0].(string), c[1].(string), c[2].(string), c[3].(bool)
		if got := policies[name].Permits(host, netip.MustParseAddr(addr)); got != want {
			t.Errorf("%s.Permits(%q, %s) = %v, Python %v", name, host, addr, got, want)
		}
	}
}

func TestFnmatch(t *testing.T) {
	cases := []struct {
		name, pattern string
		want          bool
	}{
		{"a.b.c", "*.c", true},
		{"a/b.c", "*.c", true},
		{"abc", "a?c", true},
		{"ac", "a?c", false},
		{"host-5", "host-[0-9]", true},
		{"host-x", "host-[!0-9]", true},
		{"host-5", "host-[!0-9]", false},
		{"a[b", "a[b", true},
		{"a]", "a[]]", true},
		{"a.c", "a.c", true},
		{"abc", "a.c", false},
		{"x", "[z-a]", false},
	}
	for _, c := range cases {
		if got := Fnmatch(c.name, c.pattern); got != c.want {
			t.Errorf("Fnmatch(%q, %q) = %v, want %v", c.name, c.pattern, got, c.want)
		}
	}
}

type fakeResolver map[string][]netip.Addr

func (f fakeResolver) LookupNetIP(_ context.Context, _, host string) ([]netip.Addr, error) {
	a, ok := f[host]
	if !ok {
		return nil, errors.New("no such host")
	}
	return a, nil
}

func TestCheckURL(t *testing.T) {
	policy, _ := NewAddressPolicy(false, nil)
	g := &Guard{Policy: policy, Resolver: fakeResolver{
		"public.test": {netip.MustParseAddr("93.184.216.34")},
		"mixed.test":  {netip.MustParseAddr("93.184.216.34"), netip.MustParseAddr("10.0.0.1")},
		"empty.test":  {},
	}}
	ctx := context.Background()
	cases := []struct{ url, err string }{
		{"https://public.test/x", ""},
		{"http://8.8.8.8/", ""},
		{"ftp://public.test/", "URL scheme 'ftp' is not allowed; use http or https"},
		{"http:///path", "URL has no host"},
		{"http://nowhere.test/", "Could not resolve host 'nowhere.test'"},
		{"http://empty.test/", "Host 'empty.test' has no address"},
		{"http://mixed.test/", "URL host 'mixed.test' resolves to non-public address 10.0.0.1; refusing request"},
		{"http://[::ffff:127.0.0.1]/", "URL host '::ffff:127.0.0.1' resolves to non-public address ::ffff:127.0.0.1; refusing request"},
	}
	for _, c := range cases {
		_, err := g.CheckURL(ctx, c.url)
		switch {
		case c.err == "" && err != nil:
			t.Errorf("%s: %v", c.url, err)
		case c.err != "" && (err == nil || err.Error() != c.err):
			t.Errorf("%s: got %v, want %q", c.url, err, c.err)
		case c.err != "" && !errors.Is(err, ErrUnsafe):
			t.Errorf("%s: %v is not ErrUnsafe", c.url, err)
		}
	}
	open, _ := NewAddressPolicy(true, nil)
	if _, err := (&Guard{Policy: open, Resolver: fakeResolver{}}).CheckURL(ctx, "http://10.0.0.1/"); err != nil {
		t.Errorf("allow_private refused: %v", err)
	}
}
