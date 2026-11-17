package domain

import (
	"strings"
	"testing"
)

func str(s string) *string { return &s }

func deref(p *string) string {
	if p == nil {
		return "<nil>"
	}
	return *p
}

func TestChannelRulesInOrder(t *testing.T) {
	own := []string{"example.com"}
	cases := []struct {
		ref, path, utm *string
		want           string
	}{
		{str("google.com"), nil, str("newsletter"), "campaign"},
		{str("www.Google.de"), nil, nil, "search"},
		{str("news.yandex.ru"), nil, nil, "search"},
		{str("duckduckgo.com"), nil, nil, "search"},
		{str("t.me"), nil, nil, "social"},
		{str("blog.somebody.dev"), str("/skills/x"), nil, "referral"},
		{str("docs.example.com"), str("/skills/x"), nil, "skills_catalog"},
		{str("example.com"), str("/pricing"), nil, "direct"},
		{nil, str("/ru/skills/y"), nil, "skills_catalog"},
		{nil, nil, nil, "direct"},
	}
	for i, c := range cases {
		if got := ClassifyChannel(c.ref, c.path, c.utm, own); got != c.want {
			t.Errorf("%d: %s, want %s", i, got, c.want)
		}
	}
}

func TestAttributionFromTheLandingQuery(t *testing.T) {
	long := strings.Repeat("a", 80)
	a := AttributionFromRequestURL(str("https://app.example.test/self-service/registration?aa_ch=bogus&aa_ref=reddit.com&aa_lh=example.com&aa_lp=/skills/pdf-tools&utm_medium=%20cpc%20&utm_campaign="+long), nil)
	if a.Channel != "social" || deref(a.ReferrerHost) != "reddit.com" || deref(a.LandingHost) != "example.com" ||
		deref(a.LandingPath) != "/skills/*" || deref(a.UTMMedium) != "cpc" || len(deref(a.UTMCampaign)) != 64 || a.UTMSource != nil {
		t.Fatalf("%+v", a)
	}
	if a := AttributionFromRequestURL(str("https://x/?aa_ch=skills_catalog&aa_lp=/pricing"), nil); a.Channel != "skills_catalog" || deref(a.LandingPath) != "/pricing" {
		t.Fatalf("%+v", a)
	}
	if a := AttributionFromRequestURL(nil, nil); a.Channel != "direct" || a.LandingPath != nil {
		t.Fatalf("%+v", a)
	}
}

func TestParseOwnDomains(t *testing.T) {
	got, err := ParseOwnDomains(" Example.com, docs.example.org ")
	if err != nil || len(got) != 2 || got[0] != "example.com" || got[1] != "docs.example.org" {
		t.Fatal(got, err)
	}
	if got, err := ParseOwnDomains(""); err != nil || got != nil {
		t.Fatal(got, err)
	}
	for _, bad := range []string{"localhost", "example.123", "-x.com", "a..b", "example.com,"} {
		if _, err := ParseOwnDomains(bad); err == nil {
			t.Errorf("%q passed", bad)
		}
	}
}

func TestPseudonymizeIsKeyedByTheInstallation(t *testing.T) {
	a, b := Pseudonymize("install-1", "identity"), Pseudonymize("install-2", "identity")
	if len(a) != 16 || a == b || a != Pseudonymize("install-1", "identity") {
		t.Fatal(a, b)
	}
	if got := Pseudonymize("k", "v"); got != "c5d4be1992d50d3b" {
		t.Fatal(got)
	}
}
