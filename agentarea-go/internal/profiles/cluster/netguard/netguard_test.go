package netguard

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

type resolver map[string][]netip.Addr

func (r resolver) LookupNetIP(_ context.Context, _, host string) ([]netip.Addr, error) {
	if a, ok := r[host]; ok {
		return a, nil
	}
	return nil, errors.New("no such host")
}

func noProxy(*url.URL) (*url.URL, error) { return nil, nil }

func newOutbound(t *testing.T, cfg kernel.Config, r resolver, proxy func(*url.URL) (*url.URL, error)) *Outbound {
	t.Helper()
	trust, err := LoadTrust("")
	if err != nil {
		t.Fatal(err)
	}
	o, err := New(cfg, trust, nil, Options{Resolver: r, Proxy: proxy})
	if err != nil {
		t.Fatal(err)
	}
	return o
}

func TestMemberRequestIsPinnedToVettedAddress(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, r.Host)
	}))
	defer srv.Close()
	_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
	loop := netip.MustParseAddr("127.0.0.1")
	o := newOutbound(t, kernel.Config{PrivateAllowlist: []string{"svc.local"}},
		resolver{"svc.local": {loop}, "evil.test": {loop}}, noProxy)
	c := o.Client(kernel.Member, 0)

	resp, err := c.Get("http://svc.local:" + port + "/")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if string(body) != "svc.local:"+port {
		t.Fatalf("Host header %q", body)
	}

	_, err = c.Get("http://evil.test:" + port + "/")
	var blocked *kernel.BlockedError
	if !errors.As(err, &blocked) || !strings.Contains(err.Error(), "URL host 'evil.test' resolves to non-public address 127.0.0.1; refusing request") {
		t.Fatalf("evil.test: %v", err)
	}
	if _, err := c.Get("ftp://svc.local/"); err == nil || !strings.Contains(err.Error(), "URL scheme 'ftp' is not allowed") {
		t.Fatalf("ftp: %v", err)
	}
}

func TestMemberRedirectHopIsVetted(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://evil.test"+r.Host[strings.LastIndex(r.Host, ":"):]+"/", http.StatusFound)
	}))
	defer srv.Close()
	_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
	loop := netip.MustParseAddr("127.0.0.1")
	o := newOutbound(t, kernel.Config{PrivateAllowlist: []string{"svc.local"}},
		resolver{"svc.local": {loop}, "evil.test": {loop}}, noProxy)
	_, err := o.Client(kernel.Member, 0).Get("http://svc.local:" + port + "/")
	if !errors.Is(err, kernel.ErrUnsafe) {
		t.Fatalf("redirect to a blocked host: %v", err)
	}
}

func TestMemberMovesOnFromRefusedAddress(t *testing.T) {
	var dialed []string
	dial := func(_ context.Context, _, address string) (net.Conn, error) {
		dialed = append(dialed, address)
		if strings.HasPrefix(address, "10.0.0.1:") {
			return nil, &net.OpError{Op: "dial", Err: os.NewSyscallError("connect", syscall.ECONNREFUSED)}
		}
		client, server := net.Pipe()
		_ = server.Close()
		return client, nil
	}
	trust, _ := LoadTrust("")
	o, err := New(kernel.Config{AllowPrivate: true}, trust, nil, Options{
		Resolver: resolver{"two.local": {netip.MustParseAddr("10.0.0.1"), netip.MustParseAddr("10.0.0.2")}},
		Proxy:    noProxy, Dial: dial,
	})
	if err != nil {
		t.Fatal(err)
	}
	conn, err := o.Dialer().DialContext(context.Background(), "tcp", "two.local:25")
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	_ = conn.Close()
	if strings.Join(dialed, " ") != "10.0.0.1:25 10.0.0.2:25" {
		t.Fatalf("dialed %v", dialed)
	}
}

func TestMemberThroughProxyGoesByName(t *testing.T) {
	var seen string
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.URL.String()
		_, _ = io.WriteString(w, "proxied")
	}))
	defer proxy.Close()
	proxyURL, _ := url.Parse(proxy.URL)
	o := newOutbound(t, kernel.Config{}, resolver{"public.test": {netip.MustParseAddr("93.184.216.34")}},
		func(*url.URL) (*url.URL, error) { return proxyURL, nil })
	resp, err := o.Client(kernel.Member, 0).Get("http://public.test/x")
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	if seen != "http://public.test/x" {
		t.Fatalf("proxy saw %q", seen)
	}
}

func TestMemberDialerWording(t *testing.T) {
	o := newOutbound(t, kernel.Config{}, resolver{"lan.test": {netip.MustParseAddr("10.0.0.5")}}, noProxy)
	_, err := o.Dialer().DialContext(context.Background(), "tcp", "lan.test:25")
	if err == nil || err.Error() != "Host 'lan.test' resolves to non-public address 10.0.0.5; refusing to connect" {
		t.Fatalf("got %v", err)
	}
}

func TestLoadTrust(t *testing.T) {
	dir := t.TempDir()
	bad := filepath.Join(dir, "bad.pem")
	if err := os.WriteFile(bad, []byte("not a certificate"), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{bad, filepath.Join(dir, "missing.pem")} {
		_, err := LoadTrust(path)
		if err == nil || !strings.HasPrefix(err.Error(), "AGENTAREA_HTTP_EXTRA_CA_CERTS="+path+" names no readable PEM file of CA certificates: ") {
			t.Fatalf("%s: %v", path, err)
		}
	}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	defer srv.Close()
	ca := filepath.Join(dir, "ca.pem")
	if err := os.WriteFile(ca, pemOf(srv.Certificate().Raw), 0o600); err != nil {
		t.Fatal(err)
	}
	trust, err := LoadTrust(ca)
	if err != nil {
		t.Fatal(err)
	}
	o, err := New(kernel.Config{}, trust, nil, Options{Proxy: noProxy})
	if err != nil {
		t.Fatal(err)
	}
	resp, err := o.Client(kernel.Internal, 0).Get(srv.URL)
	if err != nil {
		t.Fatalf("extra CA not trusted: %v", err)
	}
	_ = resp.Body.Close()
}

func TestPublicIgnoresMemberAllowlist(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer srv.Close()
	_, port, _ := net.SplitHostPort(srv.Listener.Addr().String())
	loop := netip.MustParseAddr("127.0.0.1")
	o := newOutbound(t, kernel.Config{PrivateAllowlist: []string{"svc.local"}}, resolver{"svc.local": {loop}}, noProxy)

	if _, err := o.Client(kernel.Member, 0).Get("http://svc.local:" + port + "/"); err != nil {
		t.Fatalf("member: %v", err)
	}
	_, err := o.Client(kernel.Public, 0).Get("http://svc.local:" + port + "/")
	if !errors.Is(err, kernel.ErrUnsafe) {
		t.Fatalf("public reached an allowlisted private host: %v", err)
	}
}
