package connections

import "testing"

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
