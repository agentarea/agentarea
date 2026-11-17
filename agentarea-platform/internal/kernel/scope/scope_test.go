package scope

import (
	"errors"
	"fmt"
	"testing"
)

func TestNewWorkspaceRefusesNoID(t *testing.T) {
	if _, err := NewWorkspace("", "acme"); !errors.Is(err, ErrNoWorkspace) {
		t.Fatalf("want ErrNoWorkspace, got %v", err)
	}
	w, err := NewWorkspace("ws-1", "acme")
	if err != nil || w.ID() != "ws-1" || w.Slug() != "acme" || w.IsZero() {
		t.Fatalf("unexpected %v %v", w, err)
	}
	if !(Workspace{}).IsZero() {
		t.Fatal("zero value must name no workspace")
	}
}

func TestAccessDeniedMessages(t *testing.T) {
	e := &AccessDeniedError{ResourceType: "agent", ResourceID: "a1", CurrentWorkspace: "w1", ResourceWorkspace: "w2", UserID: "u1"}
	want := "Access denied to agent 'a1'. Resource belongs to workspace 'w2' but user is in workspace 'w1' (workspace_id=w1, user_id=u1, resource_id=a1)"
	if e.Error() != want {
		t.Fatalf("got %q", e.Error())
	}
	m := &MissingContextError{Field: "workspace_id"}
	if m.SafeDetail() != "Request must include valid workspace_id information" {
		t.Fatalf("got %q", m.SafeDetail())
	}
}

// Expected values produced by agentarea_common.workspaces.slug and
// agentarea_common.utils.slug.
func TestSlugifyWorkspace(t *testing.T) {
	cases := map[string]string{
		"Acme Corp":                            "acme-corp",
		"  --Hello__World--  ":                 "hello-world",
		"!!!":                                  "workspace",
		"Привет":                               "workspace",
		"İstanbul":                             "i-stanbul",
		"0123abcd-0123-abcd-0123-0123456789ab": "0123abcd-0123-abcd-0123-0123456789ab-ws",
		"-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbb": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-yy":   "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
	}
	for in, want := range cases {
		if got := SlugifyWorkspace(in, "workspace"); got != want {
			t.Errorf("SlugifyWorkspace(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestEntitySlug(t *testing.T) {
	cases := map[string]string{
		"My Agent":     "my-agent",
		"Café Déjà Vu": "cafe-deja-vu",
		"日本語":          "item",
		"ｆｕｌｌｗｉｄｔｈ 1":  "fullwidth-1",
		"--a--b--":     "a-b",
	}
	for in, want := range cases {
		if got := EntitySlug(in); got != want {
			t.Errorf("EntitySlug(%q) = %q, want %q", in, got, want)
		}
	}
	long := ""
	for range 60 {
		long += "ab "
	}
	want := "ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-ab-a"
	if got := EntitySlug(long); got != want {
		t.Fatalf("EntitySlug(long) = %q", got)
	}
}

func TestValidWorkspaceSlug(t *testing.T) {
	for s, want := range map[string]bool{
		"acme": true, "acme-2": true, "a-b-c": true,
		"": false, "-a": false, "a-": false, "a--b": false, "A": false, "a_b": false,
	} {
		if ValidWorkspaceSlug(s) != want {
			t.Errorf("ValidWorkspaceSlug(%q) != %v", s, want)
		}
	}
	long := make([]byte, WorkspaceSlugColumnLength+1)
	for i := range long {
		long[i] = 'a'
	}
	if ValidWorkspaceSlug(string(long)) {
		t.Fatal("over-long slug accepted")
	}
}

func TestUniqueSlug(t *testing.T) {
	taken := map[string]bool{"a": true, "a-2": true}
	got, err := UniqueSlug("a", func(c string) (bool, error) { return taken[c], nil })
	if err != nil || got != "a-3" {
		t.Fatalf("got %q %v", got, err)
	}
	_, err = UniqueSlug("a", func(string) (bool, error) { return true, nil })
	if err == nil {
		t.Fatal("want exhaustion error")
	}
	boom := fmt.Errorf("boom")
	if _, err := UniqueSlug("a", func(string) (bool, error) { return false, boom }); !errors.Is(err, boom) {
		t.Fatalf("want boom, got %v", err)
	}
}
