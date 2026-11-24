package connections

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"strings"
	"testing"
)

func TestParseOAuthAppsInstallURL(t *testing.T) {
	const base = `"issuer":"https://gh","client_id":"c","client_secret":"s","authorization_endpoint":"https://gh/a","token_endpoint":"https://gh/t"`
	apps, err := parseOAuthApps(`[{` + base + `,"install_url":"https://github.com/apps/x/installations/new"}]`)
	if err != nil || apps[0].InstallURL != "https://github.com/apps/x/installations/new" {
		t.Fatalf("apps %+v err %v", apps, err)
	}
	if apps, err := parseOAuthApps(`[{` + base + `}]`); err != nil || apps[0].InstallURL != "" {
		t.Fatalf("without install_url: %+v %v", apps, err)
	}
	for _, bad := range []string{"http://github.com/apps/x/installations/new", "github.com/apps/x", "https://"} {
		if _, err := parseOAuthApps(`[{` + base + `,"install_url":"` + bad + `"}]`); err == nil {
			t.Fatalf("install_url %q accepted", bad)
		}
	}
}

func testPEM(t *testing.T, pkcs8 bool) string {
	t.Helper()
	k, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	if pkcs8 {
		der, err := x509.MarshalPKCS8PrivateKey(k)
		if err != nil {
			t.Fatal(err)
		}
		return string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(k)}))
}

func TestParseOAuthAppsInstallationTokens(t *testing.T) {
	const base = `"issuer":"https://gh","client_id":"c","client_secret":"s","authorization_endpoint":"https://gh/a","token_endpoint":"https://gh/t"`
	key := func(pemText string) string { b, _ := json.Marshal(pemText); return string(b) }
	for _, pkcs8 := range []bool{false, true} {
		for _, id := range []string{`123`, `"123"`} {
			apps, err := parseOAuthApps(`[{` + base + `,"app_id":` + id + `,"private_key":` + key(testPEM(t, pkcs8)) + `,"api_url":"https://api.gh/"}]`)
			if err != nil {
				t.Fatalf("pkcs8=%v app_id %s: %v", pkcs8, id, err)
			}
			a := apps[0]
			if !a.MintsInstallationTokens() || a.AppID != "123" || a.APIURL != "https://api.gh" {
				t.Fatalf("app_id %q api_url %q key set %v", a.AppID, a.APIURL, a.InstallationKey != nil)
			}
		}
	}
	if apps, err := parseOAuthApps(`[{` + base + `}]`); err != nil || apps[0].MintsInstallationTokens() {
		t.Fatalf("without the fields: err %v", err)
	}
	good := key(testPEM(t, false))
	bad := map[string]string{
		"app_id only":        `,"app_id":1`,
		"no api_url":         `,"app_id":1,"private_key":` + good,
		"no private_key":     `,"app_id":1,"api_url":"https://api.gh"`,
		"no app_id":          `,"private_key":` + good + `,"api_url":"https://api.gh"`,
		"bad pem":            `,"app_id":1,"private_key":"not a key","api_url":"https://api.gh"`,
		"pem not a key":      `,"app_id":1,"private_key":` + key(string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: []byte{1, 2, 3}}))) + `,"api_url":"https://api.gh"`,
		"http api_url":       `,"app_id":1,"private_key":` + good + `,"api_url":"http://api.gh"`,
		"app_id not integer": `,"app_id":1.5,"private_key":` + good + `,"api_url":"https://api.gh"`,
		"app_id zero":        `,"app_id":0,"private_key":` + good + `,"api_url":"https://api.gh"`,
	}
	for name, extra := range bad {
		_, err := parseOAuthApps(`[{` + base + extra + `}]`)
		if err == nil {
			t.Fatalf("%s accepted", name)
		}
		if strings.Contains(err.Error(), "BEGIN") || strings.Contains(err.Error(), "not a key") {
			t.Fatalf("%s: error echoes the key: %v", name, err)
		}
	}
}
