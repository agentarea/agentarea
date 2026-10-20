package egress

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestMemberHost(t *testing.T) {
	cases := map[string]bool{
		"https://api.example.com/bot{credentials.token}/x": false,
		"{config.url}":                    true,
		"https://{config.host}/feed":      true,
		"https://example.com/?u={cursor}": false,
	}
	for tmpl, want := range cases {
		if got := MemberHost(tmpl); got != want {
			t.Errorf("MemberHost(%q) = %v, want %v", tmpl, got, want)
		}
	}
}

func TestAMemberClientCannotReachLoopback(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer server.Close()

	p, _ := NewPolicy(false, nil)
	_, err := p.Client(true, 5*time.Second).Get(server.URL)
	if err == nil || !strings.Contains(err.Error(), "private address") {
		t.Fatalf("err = %v, want a private address refusal", err)
	}
	resp, err := p.Client(false, 5*time.Second).Get(server.URL)
	if err != nil {
		t.Fatalf("an entry's own host was refused: %v", err)
	}
	_ = resp.Body.Close()
}

func TestTheAllowlistOpensAHostOrANetwork(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer server.Close()

	for _, allow := range [][]string{{"127.0.0.0/8"}, {"127.0.0.1"}} {
		p, err := NewPolicy(false, allow)
		if err != nil {
			t.Fatalf("NewPolicy: %v", err)
		}
		resp, err := p.Client(true, 5*time.Second).Get(server.URL)
		if err != nil {
			t.Fatalf("allowlist %v: %v", allow, err)
		}
		_ = resp.Body.Close()
	}
}

func TestDialerRefusesPrivateAddressesForAMemberHost(t *testing.T) {
	p, _ := NewPolicy(false, nil)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer listener.Close()
	if _, err := p.Dialer(true, "mail.internal").DialContext(context.Background(), "tcp", listener.Addr().String()); err == nil {
		t.Fatal("dialed a loopback address for a member host")
	}
}
