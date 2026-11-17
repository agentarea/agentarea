package domain

import (
	"strings"
	"testing"
	"time"
)

func TestPyRepr(t *testing.T) {
	for in, want := range map[string]string{
		"Workspace":    `'Workspace'`,
		"it's":         `"it's"`,
		`a'b"c`:        `'a\'b"c'`,
		"tab\there":    `'tab\there'`,
		`back\`:        `'back\\'`,
		"\x00\x7f":     `'\x00\x7f'`,
		"\u00e9\u00a0": "'\u00e9\\xa0'",
		"\u200b":       "'\\u200b'",
		"日本":           `'日本'`,
		"":             `''`,
	} {
		if got := PyRepr(in); got != want {
			t.Errorf("PyRepr(%q) = %s, want %s", in, got, want)
		}
	}
}

func TestMembersOrderKnownJoinsFirst(t *testing.T) {
	t0 := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	got := Members([]string{"z", "c", "a", "b"}, []MembershipRow{
		{UserID: "b", CreatedAt: t0.Add(time.Hour)}, {UserID: "c", CreatedAt: t0}, {UserID: "gone", CreatedAt: t0},
	})
	var order []string
	for _, m := range got {
		order = append(order, m.UserID)
	}
	if strings.Join(order, ",") != "c,b,a,z" || got[3].JoinedAt != nil {
		t.Fatalf("order %v", order)
	}
}

func TestLogoContentType(t *testing.T) {
	for data, want := range map[string]string{
		"\x89PNG\r\n\x1a\nrest": "image/png", "\xff\xd8\xffxx": "image/jpeg", "RIFF1234WEBP": "image/webp",
		"RIFF1234WEB": "", "GIF89a": "", "": "",
	} {
		if got, _ := LogoContentType([]byte(data)); got != want {
			t.Errorf("%q: %q, want %q", data, got, want)
		}
	}
}

func TestExplorerTables(t *testing.T) {
	if VerbToBit("delete") != "can_manage" || VerbToBit("fly") != "fly" || CheckableBit("fly") {
		t.Fatal("verb table")
	}
	if g, ok := LegacyRelationToGrant("operators"); !ok || g != "manager" {
		t.Fatal("legacy relations")
	}
	if Color(KindAgent, 6) != "#8b5cf6" {
		t.Fatal("palette wraps")
	}
}

func TestIdentityForFallsBackOnlyForTheCaller(t *testing.T) {
	me := "me@x.co"
	if got := IdentityFor("other", nil, "me", &me); got.Email != nil || got.DisplayName != nil {
		t.Fatalf("another user got the caller's email: %+v", got)
	}
	if got := IdentityFor("me", nil, "me", &me); *got.Email != me || *got.DisplayName != me {
		t.Fatalf("caller %+v", got)
	}
}
