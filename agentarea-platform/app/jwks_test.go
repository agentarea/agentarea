package app

import (
	"bytes"
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

type jwk struct {
	Kty, Crv, X, Y, D, Alg, Kid, Use string
}

func decodeJWKS(t *testing.T, raw []byte) jwk {
	t.Helper()
	var set struct{ Keys []jwk }
	if err := json.Unmarshal(raw, &set); err != nil || len(set.Keys) != 1 {
		t.Fatalf("jwks %s: %v", raw, err)
	}
	return set.Keys[0]
}

func TestNewJWKSPairsAPrivateKeyWithItsPublicPoint(t *testing.T) {
	private, public, err := newJWKS("k1", rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	priv, pub := decodeJWKS(t, private), decodeJWKS(t, public)
	if pub.D != "" {
		t.Fatal("the public JWKS carries the private scalar")
	}
	if pub.Kty != "EC" || pub.Crv != "P-256" || pub.Alg != "ES256" || pub.Kid != "k1" || pub.Use != "sig" {
		t.Fatalf("public key %+v", pub)
	}
	if priv.X != pub.X || priv.Y != pub.Y || priv.Kid != "k1" {
		t.Fatalf("private %+v public %+v", priv, pub)
	}
	d, _ := base64.RawURLEncoding.DecodeString(priv.D)
	key, err := ecdh.P256().NewPrivateKey(d)
	if err != nil {
		t.Fatal(err)
	}
	x, _ := base64.RawURLEncoding.DecodeString(pub.X)
	y, _ := base64.RawURLEncoding.DecodeString(pub.Y)
	if len(x) != 32 || len(y) != 32 {
		t.Fatalf("coordinates are %d and %d bytes, not 32", len(x), len(y))
	}
	if !bytes.Equal(key.PublicKey().Bytes(), append(append([]byte{4}, x...), y...)) {
		t.Fatal("x and y are not the private key's public point")
	}
}

func TestEnsureJWKSSecretNeverReplacesAnExistingKey(t *testing.T) {
	var created []byte
	exists := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/namespaces/ns/secrets/jwks":
			if exists {
				w.WriteHeader(http.StatusOK)
				return
			}
			w.WriteHeader(http.StatusNotFound)
		case r.Method == http.MethodPost && r.URL.Path == "/api/v1/namespaces/ns/secrets":
			created, _ = io.ReadAll(r.Body)
			exists = true
			w.WriteHeader(http.StatusCreated)
		default:
			w.WriteHeader(http.StatusTeapot)
		}
	}))
	defer srv.Close()
	api := secretsAPI{base: srv.URL, token: "tok", client: srv.Client()}

	made, err := ensureJWKSSecret(context.Background(), api, "ns", "jwks", "k1")
	if err != nil || !made {
		t.Fatalf("first run: made=%v err=%v", made, err)
	}
	var secret struct {
		Metadata struct {
			Name        string
			Annotations map[string]string
		}
		Data map[string][]byte
	}
	if err := json.Unmarshal(created, &secret); err != nil {
		t.Fatal(err)
	}
	if secret.Metadata.Name != "jwks" || secret.Metadata.Annotations["helm.sh/resource-policy"] != "keep" {
		t.Fatalf("metadata %+v", secret.Metadata)
	}
	if decodeJWKS(t, secret.Data["jwks.json"]).D == "" || decodeJWKS(t, secret.Data["jwks_b64"]).D != "" ||
		!bytes.Equal(secret.Data["jwks_b64"], secret.Data["jwks_public.json"]) {
		t.Fatalf("data keys %v", secret.Data)
	}

	created = nil
	made, err = ensureJWKSSecret(context.Background(), api, "ns", "jwks", "k1")
	if err != nil || made || created != nil {
		t.Fatalf("second run replaced the key: made=%v err=%v", made, err)
	}

	api.token = "wrong"
	if _, err := ensureJWKSSecret(context.Background(), api, "ns", "jwks", "k1"); err == nil {
		t.Fatal("an unauthorized read taken as absent")
	}
}
