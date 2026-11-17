package app

import (
	"bytes"
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	serviceAccountDir = "/var/run/secrets/kubernetes.io/serviceaccount"
	inClusterAPI      = "https://kubernetes.default.svc"
)

// runKratosJWKS is the Kratos JWKS bootstrap: the Secret holding the ES256 key
// Kratos signs session JWTs with is created once and never replaced, so tokens
// already issued keep verifying across upgrades.
func (b *Build) runKratosJWKS(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("kratos-jwks", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	secret := fs.String("secret", "", "name of the Secret to create")
	kid := fs.String("kid", "", "key id the JWKS names")
	namespace := fs.String("namespace", "", "namespace of the Secret")
	if err := fs.Parse(args); err != nil || fs.NArg() > 0 || *secret == "" || *kid == "" || *namespace == "" {
		return fmt.Errorf("%w: kratos-jwks --secret name --kid id --namespace ns", ErrUsage)
	}
	api, err := inClusterSecrets()
	if err != nil {
		return err
	}
	created, err := ensureJWKSSecret(ctx, api, *namespace, *secret, *kid)
	if err != nil {
		return err
	}
	if created {
		_, _ = fmt.Fprintf(b.stdout, "Secret %s created.\n", *secret)
	} else {
		_, _ = fmt.Fprintf(b.stdout, "Secret %s already exists.\n", *secret)
	}
	return nil
}

// secretsAPI is the Kubernetes API's Secrets endpoint, reached with a bearer token.
type secretsAPI struct {
	base   string
	token  string
	client *http.Client
}

func inClusterSecrets() (secretsAPI, error) {
	token, err := os.ReadFile(filepath.Join(serviceAccountDir, "token"))
	if err != nil {
		return secretsAPI{}, fmt.Errorf("service account token: %w", err)
	}
	ca, err := os.ReadFile(filepath.Join(serviceAccountDir, "ca.crt"))
	if err != nil {
		return secretsAPI{}, fmt.Errorf("service account CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(ca) {
		return secretsAPI{}, errors.New("service account CA: no certificate")
	}
	client := &http.Client{Timeout: 30 * time.Second, Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12}}}
	return secretsAPI{base: inClusterAPI, token: strings.TrimSpace(string(token)), client: client}, nil
}

func (a secretsAPI) do(ctx context.Context, method, path string, body []byte) (int, []byte, error) {
	req, err := http.NewRequestWithContext(ctx, method, a.base+path, bytes.NewReader(body))
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Authorization", "Bearer "+a.token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := a.client.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	out, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	return resp.StatusCode, out, err
}

// ensureJWKSSecret creates the Secret unless it exists; it reports whether it did.
func ensureJWKSSecret(ctx context.Context, api secretsAPI, namespace, name, kid string) (bool, error) {
	secrets := "/api/v1/namespaces/" + url.PathEscape(namespace) + "/secrets"
	status, body, err := api.do(ctx, http.MethodGet, secrets+"/"+url.PathEscape(name), nil)
	if err != nil {
		return false, fmt.Errorf("read secret %s: %w", name, err)
	}
	switch status {
	case http.StatusOK:
		return false, nil
	case http.StatusNotFound:
	default:
		return false, fmt.Errorf("read secret %s: HTTP %d: %s", name, status, body)
	}
	private, public, err := newJWKS(kid, rand.Reader)
	if err != nil {
		return false, err
	}
	payload, err := json.Marshal(map[string]any{
		"apiVersion": "v1",
		"kind":       "Secret",
		"metadata":   map[string]any{"name": name, "annotations": map[string]string{"helm.sh/resource-policy": "keep"}},
		"type":       "Opaque",
		"data": map[string][]byte{
			"jwks.json":        private,
			"jwks_public.json": public,
			"jwks_b64":         public,
		},
	})
	if err != nil {
		return false, err
	}
	status, body, err = api.do(ctx, http.MethodPost, secrets, payload)
	if err != nil {
		return false, fmt.Errorf("create secret %s: %w", name, err)
	}
	if status != http.StatusCreated {
		return false, fmt.Errorf("create secret %s: HTTP %d: %s", name, status, body)
	}
	return true, nil
}

// newJWKS makes one P-256 signing key as a private and a public JWKS.
func newJWKS(kid string, random io.Reader) (private, public []byte, err error) {
	key, err := ecdh.P256().GenerateKey(random)
	if err != nil {
		return nil, nil, fmt.Errorf("generate key: %w", err)
	}
	point := key.PublicKey().Bytes() // 0x04 || X || Y
	b64 := base64.RawURLEncoding.EncodeToString
	pub := map[string]string{"kty": "EC", "crv": "P-256", "x": b64(point[1:33]), "y": b64(point[33:]), "alg": "ES256", "kid": kid, "use": "sig"}
	priv := map[string]string{"d": b64(key.Bytes())}
	for k, v := range pub {
		priv[k] = v
	}
	if private, err = json.Marshal(map[string]any{"keys": []any{priv}}); err != nil {
		return nil, nil, err
	}
	if public, err = json.Marshal(map[string]any{"keys": []any{pub}}); err != nil {
		return nil, nil, err
	}
	return private, public, nil
}
