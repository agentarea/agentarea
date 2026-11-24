package authn

import "testing"

func TestOAuthCredentialReachesWhatWasGranted(t *testing.T) {
	cases := []struct {
		granted          []string
		api, mcp, scopes bool
	}{
		{granted: nil},
		{granted: []string{"openid", "offline_access"}},
		{granted: []string{"offline_access", OAuthScopeMCP}, mcp: true},
		{granted: []string{OAuthScopeAPI}, api: true, mcp: true, scopes: true},
		{granted: []string{OAuthScopeMCP, OAuthScopeAPI}, api: true, mcp: true, scopes: true},
	}
	for _, c := range cases {
		cred := Credential{Kind: KindOAuth, Granted: c.granted}
		if got := cred.Reaches(SurfaceAPI); got != c.api {
			t.Errorf("%v on the API: %v", c.granted, got)
		}
		if got := cred.Reaches(SurfaceMCP); got != c.mcp {
			t.Errorf("%v on MCP: %v", c.granted, got)
		}
		if got := cred.Grants(ScopeCredentials) && cred.Grants(ScopeWorkspaces); got != c.scopes {
			t.Errorf("%v grants credentials and workspaces: %v", c.granted, got)
		}
	}
}

func TestOtherCredentialsReachEverySurface(t *testing.T) {
	for _, k := range []CredentialKind{KindSession, KindAPIKey, KindTurn} {
		cred := Credential{Kind: k}
		if !cred.Reaches(SurfaceAPI) || !cred.Reaches(SurfaceMCP) {
			t.Errorf("%s", k)
		}
	}
	if s := (Credential{Kind: KindSession}); !s.Grants(ScopeCredentials) || !s.Grants(ScopeWorkspaces) {
		t.Error("a browser session lost its scopes")
	}
}
