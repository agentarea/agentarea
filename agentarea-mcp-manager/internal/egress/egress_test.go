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

func memberClient(p Policy) *http.Client {
	return &http.Client{Transport: p.Transport(), Timeout: 5 * time.Second}
}

func TestAMemberHostCannotReachLoopback(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer server.Close()

	p, _ := NewPolicy(false, nil)
	_, err := memberClient(p).Get(server.URL)
	if err == nil || !strings.Contains(err.Error(), "private address") {
		t.Fatalf("err = %v, want a private address refusal", err)
	}
}

func TestTheAllowlistOpensAHostOrANetwork(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer server.Close()

	for _, allow := range [][]string{{"127.0.0.0/8"}, {"127.0.0.1"}} {
		p, err := NewPolicy(false, allow)
		if err != nil {
			t.Fatalf("NewPolicy: %v", err)
		}
		resp, err := memberClient(p).Get(server.URL)
		if err != nil {
			t.Fatalf("allowlist %v: %v", allow, err)
		}
		_ = resp.Body.Close()
	}
}

func TestAllowPrivateOpensEveryPrivateAddress(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	defer server.Close()

	p, _ := NewPolicy(true, nil)
	resp, err := memberClient(p).Get(server.URL)
	if err != nil {
		t.Fatalf("AllowPrivate refused loopback: %v", err)
	}
	_ = resp.Body.Close()
}

func TestDialerRefusesPrivateAddressesForAMemberHost(t *testing.T) {
	p, _ := NewPolicy(false, nil)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer listener.Close()
	if _, err := p.Dialer("mail.internal").DialContext(context.Background(), "tcp", listener.Addr().String()); err == nil {
		t.Fatal("dialed a loopback address for a member host")
	}
}

func TestNewPolicyRejectsAMalformedCIDR(t *testing.T) {
	if _, err := NewPolicy(false, []string{"10.0.0.0/99"}); err == nil {
		t.Fatal("NewPolicy accepted a malformed CIDR")
	}
}
