package api

import "testing"

// TestFnmatchBracketsMatchCPython is a truth table from CPython 3 fnmatch.fnmatchcase.
func TestFnmatchBracketsMatchCPython(t *testing.T) {
	names := []string{"a", "b", "c", "d", "e", "z", "-", "]", "[", "!", "^", "&", `\\`, "x", "xy", "xzy", "tool[", "q"}
	for _, c := range []struct{ pattern, want string }{
		{"[z-a]", "000000000000000000"},
		{"[!z-a]", "111111111111010001"},
		{"[a-c]", "111000000000000000"},
		{"[!a-c]", "000111111111010001"},
		{"[", "000000001000000000"},
		{"tool[", "000000000000000010"},
		{"[]]", "000000010000000000"},
		{"[!]]", "111111101111010001"},
		{"[a-]", "100000100000000000"},
		{"[-a]", "100000100000000000"},
		{"[!-]", "111111011111010001"},
		{"[a-c-e]", "111010100000000000"},
		{"[c-a-e]", "000010100000000000"},
		{"[&&a]", "100000000001000000"},
		{"[^a]", "100000000010000000"},
		{"x[z-a]y", "000000000000000000"},
		{"[]-]", "000000110000000000"},
		{"[a-z]*", "111111000000011111"},
		{"[!]", "000000000000000000"},
		{"[[]", "000000001000000000"},
	} {
		for i, name := range names {
			want := c.want[i] == '1'
			if got := Fnmatch(name, c.pattern); got != want {
				t.Errorf("Fnmatch(%q, %q) = %v, want %v", name, c.pattern, got, want)
			}
		}
	}
}

func TestDecideToolPolicySurvivesAnEmptyRange(t *testing.T) {
	p := &Policy{Tools: &Tools{Allowed: []string{"[z-a]*"}, Denied: []string{"[!z-a]x"}}}
	if d := DecideToolPolicy(p, "read", ToolNames{NameAllows: true}); d.Action != ToolDeny {
		t.Fatalf("got %+v", d)
	}
}
