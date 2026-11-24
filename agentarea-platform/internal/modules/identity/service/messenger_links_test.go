package service

import "testing"

func TestMaskEmailKeepsTheFirstLetterAndTheDomain(t *testing.T) {
	for in, want := range map[string]string{
		"alice@example.com": "a***@example.com",
		"@example.com":      "***@example.com",
		"no-at-sign":        unnamedAccount,
		"x@":                unnamedAccount,
	} {
		if got := MaskEmail(in); got != want {
			t.Errorf("MaskEmail(%q) = %q, want %q", in, got, want)
		}
	}
}
