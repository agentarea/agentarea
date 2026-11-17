package httpx

import (
	"net/http/httptest"
	"testing"
)

func TestClientIdentityTakesTheProxysHopOnlyBehindAPrivatePeer(t *testing.T) {
	for _, c := range []struct{ peer, xff, want string }{
		{"10.0.3.7:5100", "203.0.113.9", "ip:203.0.113.9"},
		{"10.0.3.7:5100", "1.2.3.4, 203.0.113.9", "ip:203.0.113.9"},
		{"127.0.0.1:5100", "198.51.100.2", "ip:198.51.100.2"},
		{"10.0.3.7:5100", "", "ip:10.0.3.7"},
		{"10.0.3.7:5100", "not-an-ip", "ip:10.0.3.7"},
		{"198.51.100.7:5100", "203.0.113.9", "ip:198.51.100.7"},
	} {
		r := httptest.NewRequest("POST", "/oauth2/register", nil)
		r.RemoteAddr = c.peer
		if c.xff != "" {
			r.Header.Set("X-Forwarded-For", c.xff)
		}
		if got := ClientIdentity(r); got != c.want {
			t.Errorf("peer %s xff %q: %s, want %s", c.peer, c.xff, got, c.want)
		}
	}
}
