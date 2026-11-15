package domain

import (
	"fmt"
	"strings"
	"testing"
)

func TestSafeDumpYAML(t *testing.T) {
	var words []string
	for i := 1; i <= 20; i++ {
		words = append(words, fmt.Sprintf("word%02d", i))
	}
	long := strings.Join(words, " ")
	longKey := strings.Repeat("k", 130)
	cases := []struct {
		name string
		in   any
		want string
	}{
		{"empty map", YAMLMap{}, "{}\n"},
		{"scalars and empty collections", YAMLMap{
			{"a", "x"}, {"b", []any{"1", "y"}}, {"c", YAMLMap{}}, {"d", []any{}},
			{"e", true}, {"f", nil}, {"g", YAMLInt("3")}, {"h", YAMLFloat("1.5")},
		}, "a: x\nb:\n- '1'\n- y\nc: {}\nd: []\ne: true\nf: null\ng: 3\nh: 1.5\n"},
		{"implicit types are quoted", YAMLMap{
			{"a", "true"}, {"b", "yes"}, {"c", "null"}, {"d", "~"}, {"e", ""}, {"f", "1.5"},
			{"g", "0x1F"}, {"h", "2024-01-01"}, {"i", "1_000"},
		}, "a: 'true'\nb: 'yes'\nc: 'null'\nd: '~'\ne: ''\nf: '1.5'\ng: '0x1F'\nh: '2024-01-01'\ni: '1_000'\n"},
		{"indicators", YAMLMap{
			{"a", "${setup.x}"}, {"b", "a: b"}, {"c", "- x"}, {"d", "#x"}, {"e", "x #y"}, {"f", "it's"},
			{"g", "https://x.test/a?b=c"}, {"h", "@x"}, {"i", " lead"}, {"j", "trail "},
		}, "a: ${setup.x}\nb: 'a: b'\nc: '- x'\nd: '#x'\ne: 'x #y'\nf: it's\ng: https://x.test/a?b=c\nh: '@x'\ni: ' lead'\nj: 'trail '\n"},
		{"unicode plain", YAMLMap{{"a", "привет мир"}}, "a: привет мир\n"},
		{"tab is double quoted", YAMLMap{{"a", "a\tb"}}, "a: \"a\\tb\"\n"},
		{"multiline single quoted", YAMLMap{{"k", "line1\nline2"}}, "k: 'line1\n\n  line2'\n"},
		{"long plain folds", YAMLMap{{"k", long}},
			"k: " + strings.Join(words[:12], " ") + "\n  " + strings.Join(words[12:], " ") + "\n"},
		{"nested", YAMLMap{
			{"metadata", YAMLMap{{"capabilities", []any{}}}},
			{"agents", []any{YAMLMap{{"key", "a"}, {"mcps", []any{}}, {"skills", []any{"s1"}}, {"spec", YAMLMap{{"x", "y"}}}}}},
		}, "metadata:\n  capabilities: []\nagents:\n- key: a\n  mcps: []\n  skills:\n  - s1\n  spec:\n    x: y\n"},
		{"long key", YAMLMap{{longKey, "v"}}, "? " + longKey + "\n: v\n"},
		{"top-level list", []any{"a", []any{"b"}}, "- a\n- - b\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := SafeDumpYAML(tc.in); got != tc.want {
				t.Fatalf("got:\n%q\nwant:\n%q", got, tc.want)
			}
		})
	}
}
