package payment

import (
	"encoding/json"
	"testing"
	"time"
)

// Expected strings are str(Decimal(str(raw or 0)) / 10**decimals) worked
// through CPython's _pydecimal __truediv__ by hand.
func TestAtomicToUSDMatchesPythonDivision(t *testing.T) {
	for _, c := range []struct {
		raw      any
		decimals int
		want     string
	}{
		{"10000", 6, "0.01"},
		{"1", 6, "0.000001"},
		{"1500000", 6, "1.5"},
		{"1000000", 6, "1"},
		{"123456789", 6, "123.456789"},
		{"0", 6, "0"},
		{"", 6, "0"},
		{nil, 6, "0"},
		{json.Number("0"), 6, "0"},
		{json.Number("2500"), 6, "0.0025"},
		{json.Number("1.5"), 6, "0.0000015"},
		{"10", 18, "1E-17"},
		{"1000", 0, "1000"},
		{"12345678901234567890123456789", 6, "12345678901234567890123.45679"},
	} {
		got, err := atomicToUSD(c.raw, c.decimals)
		if err != nil {
			t.Errorf("%v/10^%d: %v", c.raw, c.decimals, err)
			continue
		}
		if got.String() != c.want {
			t.Errorf("%v/10^%d = %s, want %s", c.raw, c.decimals, got, c.want)
		}
	}
	for _, bad := range []any{"abc", true, "1.2.3"} {
		if _, err := atomicToUSD(bad, 6); err == nil {
			t.Errorf("%v accepted", bad)
		}
	}
}

func TestPyDumps(t *testing.T) {
	v, err := decodeJSON([]byte(`{"b":"é😀<&>\u007f","a":[1.0,1e16,0.00001,100000.0,-0,7],"c":{"z":null,"y":true}}`))
	if err != nil {
		t.Fatal(err)
	}
	ascii, err := pyDumps(v, true)
	if err != nil {
		t.Fatal(err)
	}
	if want := "{\"a\":[1.0,1e+16,1e-05,100000.0,0,7],\"b\":\"\\u00e9\\ud83d\\ude00<&>\\u007f\",\"c\":{\"y\":true,\"z\":null}}"; ascii != want {
		t.Errorf("ensure_ascii:\n%s\nwant\n%s", ascii, want)
	}
	raw, err := pyDumps(v, false)
	if err != nil {
		t.Fatal(err)
	}
	if want := "{\"a\":[1.0,1e+16,1e-05,100000.0,0,7],\"b\":\"é😀<&>\x7f\",\"c\":{\"y\":true,\"z\":null}}"; raw != want {
		t.Errorf("ensure_ascii=False:\n%s\nwant\n%s", raw, want)
	}
}

func TestPyB64Decode(t *testing.T) {
	for in, want := range map[string]string{
		"aGVsbG8=":      "hello",
		"aGVsbG8":       "",
		"aGVs bG8=":     "hello",
		"aGVsbG8=junk":  "hello",
		"aGVsbA==":      "hell",
		"Pz8_":          "???",
		"Pz8/":          "???",
		"":              "",
		"aGVsbG8=\n=":   "hello",
		"YQ==YWJj":      "a",
		"!!aGVsbG8=!!!": "hello",
	} {
		got, err := pyB64Decode(in, true)
		if want == "" && in == "aGVsbG8" {
			if err == nil {
				t.Errorf("%q: unpadded input decoded", in)
			}
			continue
		}
		if err != nil || string(got) != want {
			t.Errorf("%q: %q, %v; want %q", in, got, err, want)
		}
	}
	if _, err := pyB64Decode("a", false); err == nil {
		t.Error("one data character decoded")
	}
}

func TestParseISO(t *testing.T) {
	for in, want := range map[string]struct {
		unix  int64
		aware bool
	}{
		"2025-01-02T03:04:05Z":           {1735787045, true},
		"2025-01-02T03:04:05.123Z":       {1735787045, true},
		"2025-01-02T05:04:05+02:00":      {1735787045, true},
		"2025-01-02 03:04:05+0000":       {1735787045, true},
		"2025-01-02T03:04:05":            {1735787045, false},
		"2025-01-02":                     {1735776000, false},
		"2025-01-02T03:04":               {1735787040, false},
		"2025-01-02T03:04:05.123456789Z": {1735787045, true},
	} {
		got, aware, err := parseISO(in)
		if err != nil || got.Unix() != want.unix || aware != want.aware {
			t.Errorf("%s: %v %v %v", in, got, aware, err)
		}
	}
	for _, bad := range []string{"tomorrow", "2025-13-01", "2025-02-30T00:00:00Z", ""} {
		if _, _, err := parseISO(bad); err == nil {
			t.Errorf("%q parsed", bad)
		}
	}
	if got, _, _ := parseISO("2025-01-02T03:04:05.5Z"); got.Nanosecond() != int(500*time.Millisecond) {
		t.Errorf("fraction %d", got.Nanosecond())
	}
}
