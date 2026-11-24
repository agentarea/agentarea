package sandboxruntime

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func serverWithRSAKey(t *testing.T, bits int) (*httptest.Server, *x509.CertPool) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, bits)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "localhost"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames: []string{"localhost"}, IPAddresses: []net.IP{net.IPv4(127, 0, 0, 1)}, IsCA: true, BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {}))
	srv.TLS = &tls.Config{Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}}}
	srv.StartTLS()
	t.Cleanup(srv.Close)
	pool := x509.NewCertPool()
	pool.AddCert(cert)
	return srv, pool
}

func TestOpenSandboxTransportRefusesShortServerKey(t *testing.T) {
	for bits, wantErr := range map[int]string{1024: "below NIST minimum", 2048: ""} {
		srv, pool := serverWithRSAKey(t, bits)
		base := http.DefaultTransport.(*http.Transport).Clone()
		base.TLSClientConfig = &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12}
		guarded, err := withNISTPeerMinimums(base)
		if err != nil {
			t.Fatal(err)
		}
		resp, err := (&http.Client{Transport: guarded}).Get(srv.URL)
		if wantErr == "" {
			if err != nil {
				t.Fatalf("%d-bit key refused: %v", bits, err)
			}
			_ = resp.Body.Close()
			continue
		}
		if err == nil || !strings.Contains(err.Error(), wantErr) {
			t.Fatalf("%d-bit key: err = %v, want %q", bits, err, wantErr)
		}
		if _, err := (&http.Client{Transport: base}).Get(srv.URL); err != nil {
			t.Fatalf("unguarded base must accept the weak key, got %v", err)
		}
	}
}

func TestOpenSandboxTransportNeedsAnHTTPTransport(t *testing.T) {
	if _, err := withNISTPeerMinimums(rtFunc(func(*http.Request) (*http.Response, error) { return nil, nil })); err == nil {
		t.Fatal("a non-*http.Transport was accepted")
	}
}

type rtFunc func(*http.Request) (*http.Response, error)

func (f rtFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
