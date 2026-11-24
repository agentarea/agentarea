package httpx

import (
	"encoding/json"
	"os"
	"strconv"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

type verdict struct {
	OK    bool            `json:"ok"`
	Value json.RawMessage `json:"value"`
	Error *struct {
		Type string          `json:"type"`
		Msg  string          `json:"msg"`
		Ctx  json.RawMessage `json:"ctx"`
	} `json:"error"`
}

type validationGolden struct {
	UUID   [][2]json.RawMessage `json:"uuid"`
	Int    [][2]json.RawMessage `json:"int"`
	Bool   [][2]json.RawMessage `json:"bool"`
	Float  [][2]json.RawMessage `json:"float"`
	JSON   [][2]json.RawMessage `json:"json"`
	Status map[string]string    `json:"status_phrases"`
}

func loadValidation(t *testing.T) validationGolden {
	t.Helper()
	raw, err := os.ReadFile("testdata/validation.json")
	if err != nil {
		t.Fatal(err)
	}
	var g validationGolden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}
	return g
}

func pair(t *testing.T, p [2]json.RawMessage) (string, verdict) {
	t.Helper()
	var in string
	var v verdict
	if err := json.Unmarshal(p[0], &in); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(p[1], &v); err != nil {
		t.Fatal(err)
	}
	return in, v
}

func TestParseIntMatchesPydantic(t *testing.T) {
	for _, p := range loadValidation(t).Int {
		in, want := pair(t, p)
		got, ok := ParseInt(in)
		if ok != want.OK {
			t.Errorf("ParseInt(%q) ok=%v, pydantic %v", in, ok, want.OK)
			continue
		}
		if ok && !got.Overflow {
			var s string
			_ = json.Unmarshal(want.Value, &s)
			if strconv.FormatInt(got.Value, 10) != s {
				t.Errorf("ParseInt(%q) = %d, pydantic %s", in, got.Value, s)
			}
		}
	}
}

func TestParseBoolMatchesPydantic(t *testing.T) {
	for _, p := range loadValidation(t).Bool {
		in, want := pair(t, p)
		got, ok := ParseBool(in)
		var wantValue bool
		_ = json.Unmarshal(want.Value, &wantValue)
		if ok != want.OK || (ok && got != wantValue) {
			t.Errorf("ParseBool(%q) = %v,%v, pydantic %s,%v", in, got, ok, want.Value, want.OK)
		}
	}
}

func TestParseFloatMatchesPydantic(t *testing.T) {
	for _, p := range loadValidation(t).Float {
		in, want := pair(t, p)
		got, ok := ParseFloat(in)
		var s string
		_ = json.Unmarshal(want.Value, &s)
		if ok != want.OK || (ok && wirejson.FormatFloat(got) != s) {
			t.Errorf("ParseFloat(%q) = %v,%v, pydantic %s,%v", in, got, ok, s, want.OK)
		}
	}
}

func TestValidateUUIDMatchesPydantic(t *testing.T) {
	for _, p := range loadValidation(t).UUID {
		in, want := pair(t, p)
		got, fe := ValidateUUID(in)
		if (fe == nil) != want.OK {
			t.Errorf("ValidateUUID(%q) error %v, pydantic ok=%v", in, fe, want.OK)
			continue
		}
		if fe == nil {
			var s string
			_ = json.Unmarshal(want.Value, &s)
			if got != s {
				t.Errorf("ValidateUUID(%q) = %s, pydantic %s", in, got, s)
			}
			continue
		}
		ctx, _ := wirejson.Marshal(fe.Ctx, wirejson.Compact)
		wantCtx, _ := wirejson.Restyle(want.Error.Ctx, wirejson.Compact)
		if fe.Type != want.Error.Type || fe.Msg != want.Error.Msg || string(ctx) != string(wantCtx) {
			t.Errorf("ValidateUUID(%q) = %s %q %s, pydantic %s %q %s", in, fe.Type, fe.Msg, ctx, want.Error.Type, want.Error.Msg, wantCtx)
		}
	}
}

func TestCheckMatchesJSONLoads(t *testing.T) {
	for _, p := range loadValidation(t).JSON {
		var in string
		if err := json.Unmarshal(p[0], &in); err != nil {
			t.Fatal(err)
		}
		var want *wirejson.DecodeError
		if string(p[1]) != "null" {
			want = &wirejson.DecodeError{}
			if err := json.Unmarshal(p[1], want); err != nil {
				t.Fatal(err)
			}
		}
		got, ok := wirejson.Check([]byte(in))
		if !ok {
			t.Errorf("Check(%q): not UTF-8", in)
			continue
		}
		if (got == nil) != (want == nil) || (got != nil && *got != *want) {
			t.Errorf("Check(%q) = %+v, json.loads %+v", in, got, want)
		}
	}
}

func TestStatusPhrasesMatchPython(t *testing.T) {
	for code, phrase := range loadValidation(t).Status {
		n, _ := strconv.Atoi(code)
		if got := Title(n); got != phrase {
			t.Errorf("Title(%d) = %q, Python %q", n, got, phrase)
		}
	}
}

func TestContainsNUL(t *testing.T) {
	cases := map[string]bool{
		`{"k": "a\u0000b"}`: true,
		`{"a\u0000": 1}`:    true,
		`["\u0000"]`:        true,
		`{"k": "\\u0000"}`:  false,
		`{"k": "a"}`:        false,
		`{"k": "\u0000"`:    false,
		"{\"k\": \"\x00\"}": false,
	}
	for in, want := range cases {
		if got := wirejson.ContainsNUL([]byte(in)); got != want {
			t.Errorf("ContainsNUL(%q) = %v, want %v", in, got, want)
		}
	}
}

func TestQueryPairs(t *testing.T) {
	got := QueryPairs("a=1&b=x+y&c=%zz&d&&e=%C3%A9;f=2&g=%ff")
	want := [][2]string{{"a", "1"}, {"b", "x y"}, {"c", "%zz"}, {"d", ""}, {"e", "é;f=2"}, {"g", "�"}}
	if len(got) != len(want) {
		t.Fatalf("got %q", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("pair %d = %q, want %q", i, got[i], want[i])
		}
	}
}
