package domain_test

import (
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

const proc = "def process(event):\n    return []\n"

func TestCheckProcessorCodeRefusals(t *testing.T) {
	notDefined := "The code must define a top-level def process(event) returning a list of events or None"
	secret := func(line string) string {
		return "Line " + line + " holds what looks like a secret. A processor gets no secrets, and its code is shown to everyone who reads the stream"
	}
	cases := []struct{ name, code, want string }{
		{"empty", " \n\t", "The processor's code is empty"},
		{"too big", proc + "#" + strings.Repeat("x", domain.MaxCodeBytes), "The code is 65571 bytes; a processor holds 65536"},
		{"no indent", "def process(e):\nreturn 1\n", "The code does not parse: expected an indented block after function definition on line 1 (line 2)"},
		{"no body at eof", "def process(e):\n", "The code does not parse: expected an indented block after function definition on line 1 (line 1)"},
		{"blank lines then no indent", "while x:\n\n# c\nx\n", "The code does not parse: expected an indented block after 'while' statement on line 1 (line 4)"},
		{"unterminated", "x = \"abc\n" + proc, "The code does not parse: unterminated string literal (detected at line 1) (line 1)"},
		{"unterminated triple", "x = \"\"\"abc\n\n", "The code does not parse: unterminated triple-quoted string literal (detected at line 2) (line 1)"},
		{"never closed", "x = (1\n", "The code does not parse: '(' was never closed (line 1)"},
		{"unmatched", "x = 1)\n", "The code does not parse: unmatched ')' (line 1)"},
		{"mismatch", "x = (1]\n", "The code does not parse: closing parenthesis ']' does not match opening parenthesis '(' (line 1)"},
		{"unindent", "if x:\n  a=1\n b=2\n", "The code does not parse: unindent does not match any outer indentation level (line 3)"},
		{"unexpected indent", "x=1\n  y=2\n", "The code does not parse: unexpected indent (line 2)"},
		{"bytes mix", "x = b\"a\" \"b\"\n" + proc, "The code does not parse: cannot mix bytes and nonbytes literals (line 1)"},
		{"other name", "def proc(e):\n    return []\n", notDefined},
		{"no args", "def process():\n    return []\n", notDefined},
		{"keyword only", "def process(*, e):\n    return []\n", notDefined},
		{"kwargs only", "def process(**e):\n    return []\n", notDefined},
		{"async", "async def process(e):\n    return []\n", notDefined},
		{"nested", "class A:\n    def process(self, e):\n        return []\n", notDefined},
		{"first def wins", "def process():\n    pass\ndef process(e):\n    pass\n", notDefined},
		{"assign", "def process(e):\n    api_key = \"abc\"\n    return []\n", secret("2")},
		{"chained", proc + "a = token = \"zzz\"\n", secret("3")},
		{"annotated", proc + "token: str = \"zzz\"\n", secret("3")},
		{"one liner", proc + "if x: password = \"pw1\"\n", secret("3")},
		{"after semicolon", proc + "x = 1; secret = (\"s1\")\n", secret("3")},
		{"keyword", proc + "f(\n  1,\n  password=\"hunter2\")\n", secret("5")},
		{"default", "def process(e, token=\"t0k\"):\n    return []\n", secret("1")},
		{"annotated default", "def process(e, token: str = \"t0k\"):\n    return []\n", secret("1")},
		{"dict", proc + "d = {\n  \"x\": 1,\n  \"secret\": \"x1\"}\n", secret("3")},
		{"bearer constant", proc + "h = \"Bearer abcdefgh12\"\n", secret("3")},
		{"token shape", proc + "x = ['ghp_" + strings.Repeat("a", 24) + "']\n", secret("3")},
		{"concatenated", proc + "x = (\"sk-abcdefgh\"\n     \"ijklmnop\")\n", secret("3")},
		{"fstring literal", proc + "x = f\"xoxb-1234567890{y}\"\n", secret("3")},
		{"fstring expression", proc + "x = f\"{'AKIA" + strings.Repeat("A", 16) + "'}\"\n", secret("3")},
		{"url password", proc + "u = 'postgres://me:pw@db/x'\n", secret("3")},
		{"lowest line", proc + "a = 1\npassword = 'x'\napi_key = 'y'\n", secret("4")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := domain.CheckProcessorCode(c.code)
			if err == nil || err.Error() != c.want {
				t.Fatalf("got %v\nwant %s", err, c.want)
			}
		})
	}
}

func TestCheckProcessorCodeAccepts(t *testing.T) {
	for _, code := range []string{
		proc,
		"def process(*events):\n    return None\n",
		"def process(e, /):\n    return None\n",
		"@decorate\ndef process(e):\n    pass\n",
		"import json\n\nclass T:\n    x = 1\n\ndef process(event):\n    if event['kind'] == 'a':\n        return [{'stream': 'out', 'kind': 'b', 'data': {}}]\n",
		proc + "self_token = None\nobj.token = 'x'\ntoken = ''\ntoken = 5\nname = 'alice'\n",
		proc + "x = b'Bearer abcdefghijkl'\n",
		proc + "h = {'Authorization': 'Bearer abc'}\n",
		proc + "f = lambda token='zzz': token\n",
		proc + "x = f\"{event['kind']!r:>10} {{literal}}\"\n",
		proc + "s = 'it\\'s \\n \\x41 \\u00e9'\n",
		"def process(e):\n\treturn 1\n        \n",
		proc + "x = [\n  1,\n    2,\n]\n",
		proc + "y = 1 + \\\n  2\n",
		proc + "async def helper(token='zzz'):\n    pass\n",
	} {
		if err := domain.CheckProcessorCode(code); err != nil {
			t.Errorf("%q: %v", code, err)
		}
	}
}
