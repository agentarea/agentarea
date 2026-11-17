package analytics

import (
	"reflect"
	"testing"
)

type tally struct{ got []map[string]string }

func (t *tally) Count(name string, labels map[string]string) {
	labels["name"] = name
	t.got = append(t.got, labels)
}

func TestEnumLabel(t *testing.T) {
	for in, want := range map[string]string{
		"OK": "ok", "list_tools_timeout": "list_tools_timeout", "failed:token_exchange": "failed:token_exchange",
		"failed:Bad Code!": "failed:other", "Bad Code": "other", "": "other", "a:b:c": "a:other", "-x": "other",
	} {
		if got := EnumLabel(in); got != want {
			t.Errorf("%q: %q, want %q", in, got, want)
		}
	}
}

func TestRunRefusedSkipsBillingOutages(t *testing.T) {
	c := &tally{}
	s := func(v string) *string { return &v }
	for _, code := range []*string{nil, s("no_credits"), s("credit_limit_reached"), s("billing_unavailable"), s("billing_error"), s("account_unresolved"), s("budget")} {
		RunRefused(c, code)
	}
	var reasons []string
	for _, l := range c.got {
		reasons = append(reasons, l["reason"])
	}
	if !reflect.DeepEqual(reasons, []string{"policy_denied", "no_credits", "no_credits", "other"}) {
		t.Fatal(reasons)
	}
}

func TestHandleCountsOnlyWhileAttached(t *testing.T) {
	var nilHandle *Handle
	Count(nilHandle, "x", nil)
	Count(nil, "x", nil)
	h, c := &Handle{}, &tally{}
	Count(h, "before", nil)
	h.Attach(c)
	Count(h, "connector_check", map[string]string{"outcome": "MCP Error"})
	h.Detach()
	Count(h, "after", nil)
	if len(c.got) != 1 || c.got[0]["outcome"] != "other" || c.got[0]["name"] != "connector_check" {
		t.Fatal(c.got)
	}
}
