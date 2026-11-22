package domain

import "testing"

func TestABadToolPatternMatchesNothingInsteadOfPanicking(t *testing.T) {
	if ToolMatchesAny("search", []string{"[z-a]"}) {
		t.Fatal("a pattern that does not compile matched")
	}
}
