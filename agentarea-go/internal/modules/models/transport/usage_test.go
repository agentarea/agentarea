package transport

import (
	"encoding/json"
	"math"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

func TestUsageFromProvider(t *testing.T) {
	cases := []struct {
		name, raw string
		want      Usage
	}{
		{"openai cached tokens", `{"prompt_tokens":1000,"completion_tokens":50,"total_tokens":1050,"prompt_tokens_details":{"cached_tokens":800}}`,
			Usage{Prompt: 1000, Completion: 50, Total: 1050, CachedPrompt: 800}},
		{"anthropic shape", `{"input_tokens":100,"output_tokens":20,"cache_read_input_tokens":700,"cache_creation_input_tokens":200}`,
			Usage{Prompt: 1000, Completion: 20, Total: 1020, CachedPrompt: 700, CacheCreation: 200}},
		{"openrouter cache writes", `{"prompt_tokens":8696,"completion_tokens":12,"prompt_tokens_details":{"cached_tokens":7290,"cache_write_tokens":1404}}`,
			Usage{Prompt: 8696, Completion: 12, Total: 8708, CachedPrompt: 7290, CacheCreation: 1404}},
		{"cache_creation_tokens before cache_write_tokens", `{"prompt_tokens":10,"prompt_tokens_details":{"cache_creation_tokens":3,"cache_write_tokens":4},"cache_creation_input_tokens":5}`,
			Usage{Prompt: 10, Total: 10, CacheCreation: 3}},
		{"deepseek cache hits", `{"prompt_tokens":500,"completion_tokens":10,"total_tokens":510,"prompt_cache_hit_tokens":300,"prompt_cache_miss_tokens":200}`,
			Usage{Prompt: 500, Completion: 10, Total: 510, CachedPrompt: 300}},
		{"total absent", `{"prompt_tokens":10,"completion_tokens":5}`, Usage{Prompt: 10, Completion: 5, Total: 15}},
		{"total null", `{"prompt_tokens":10,"completion_tokens":5,"total_tokens":null}`, Usage{Prompt: 10, Completion: 5, Total: 15}},
		{"total zero", `{"prompt_tokens":10,"completion_tokens":5,"total_tokens":0}`, Usage{Prompt: 10, Completion: 5, Total: 15}},
		{"nothing reported", `{"prompt_tokens":null,"completion_tokens":null}`, Usage{}},
		{"empty", `{}`, Usage{}},
		{"prompt_tokens wins over input_tokens", `{"prompt_tokens":7,"input_tokens":100,"output_tokens":3,"completion_tokens":2}`,
			Usage{Prompt: 7, Completion: 2, Total: 9}},
		{"null prompt_tokens reads the anthropic shape", `{"prompt_tokens":null,"input_tokens":4,"output_tokens":3}`,
			Usage{Prompt: 4, Completion: 3, Total: 7}},
		{"floats truncate", `{"prompt_tokens":10.9,"completion_tokens":5.5,"total_tokens":1e2}`, Usage{Prompt: 10, Completion: 5, Total: 100}},
		{"negatives floor at zero", `{"prompt_tokens":-5,"completion_tokens":-1.5,"total_tokens":-3}`, Usage{}},
		{"non-numbers are zero", `{"prompt_tokens":"10","completion_tokens":true,"total_tokens":[1]}`, Usage{}},
		{"cached capped at prompt", `{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":50}}`, Usage{Prompt: 10, Total: 10, CachedPrompt: 10}},
		{"details not an object", `{"prompt_tokens":10,"prompt_tokens_details":"x","cache_read_input_tokens":4}`, Usage{Prompt: 10, Total: 10, CachedPrompt: 4}},
	}
	for _, tc := range cases {
		if got := UsageFromProvider(numObj(t, tc.raw)); got != tc.want {
			t.Errorf("%s: got %+v, want %+v", tc.name, got, tc.want)
		}
	}
	if got := UsageFromProvider(nil); got != (Usage{}) {
		t.Errorf("nil: %+v", got)
	}
}

func TestProviderReportedCost(t *testing.T) {
	cases := []struct {
		raw  string
		want string
	}{
		{`{"prompt_tokens":10,"cost":0.0042}`, "0.0042"},
		{`{"cost":0.5}`, "0.5"},
		{`{"cost":"0.5"}`, "0.5"},
		{`{"cost":" 0.25 "}`, "0.25"},
		{`{"cost":0}`, "0"},
		{`{"cost":3}`, "3"},
		{`{"cost":1e-05}`, "0.00001"},
		{`{"cost":0.00042}`, "0.00042"},
		{`{"cost":"1e-3"}`, "0.001"},
	}
	for _, tc := range cases {
		got := ProviderReportedCost(numObj(t, tc.raw))
		if got == nil {
			t.Errorf("%s: nil", tc.raw)
			continue
		}
		assertCost(t, tc.raw, *got, tc.want)
	}
	for _, raw := range []string{`{"cost":null}`, `{"cost":true}`, `{"cost":"n/a"}`, `{"cost":-1}`, `{"cost":"-0.5"}`,
		`{"cost":"NaN"}`, `{"cost":"Infinity"}`, `{}`, `{"cost":[1]}`, `{"cost":{"usd":1}}`} {
		if got := ProviderReportedCost(numObj(t, raw)); got != nil {
			t.Errorf("%s: got %s, want nil", raw, got)
		}
	}
}

func TestProviderReportedCostReadsTheValueJSONLoadsGives(t *testing.T) {
	if got := ProviderReportedCost(map[string]any{"cost": json.Number("-0")}); got == nil || got.String() != "0" {
		t.Errorf("differs from Python: json.loads(\"-0\") is int 0, so Decimal is \"0\"; Go gives %v", got)
	}
}

func TestProviderReportedCostOfAnOverflowingFloatIsNone(t *testing.T) {
	if got := ProviderReportedCost(map[string]any{"cost": json.Number("1e400")}); got != nil {
		t.Errorf("differs from Python: json.loads(\"1e400\") is inf, which is refused; Go reads %s", got)
	}
}

func TestPyFloatRepr(t *testing.T) {
	cases := []struct {
		f    float64
		want string
	}{
		{0.1, "0.1"}, {1e-05, "1e-05"}, {1e16, "1e+16"}, {123.0, "123.0"}, {0.0001, "0.0001"}, {1.5e-07, "1.5e-07"},
		{1e22, "1e+22"}, {12345678901234567.0, "1.2345678901234568e+16"}, {9999999999999998.0, "9999999999999998.0"},
		{1e15, "1000000000000000.0"}, {0.0, "0.0"}, {math.Copysign(0, -1), "-0.0"}, {-1.5, "-1.5"}, {0.00042, "0.00042"},
		{123456.789, "123456.789"}, {math.MaxFloat64, "1.7976931348623157e+308"}, {5e-324, "5e-324"}, {-2.5e-10, "-2.5e-10"},
		{1.0 / 3, "0.3333333333333333"}, {100.0, "100.0"}, {math.NaN(), "nan"}, {math.Inf(1), "inf"}, {math.Inf(-1), "-inf"},
	}
	for _, tc := range cases {
		if got := PyFloatRepr(tc.f); got != tc.want {
			t.Errorf("PyFloatRepr(%v) = %q, want %q", tc.f, got, tc.want)
		}
	}
}

func TestPyNumberStr(t *testing.T) {
	cases := map[string]string{"42": "42", "-7": "-7", "1E5": "100000.0", "0.00042": "0.00042", "1.0": "1.0", "2.50": "2.5",
		"123456789012345678901234567890": "123456789012345678901234567890", "1e-7": "1e-07"}
	for in, want := range cases {
		if got := PyNumberStr(json.Number(in)); got != want {
			t.Errorf("PyNumberStr(%s) = %q, want %q", in, got, want)
		}
	}
}

func TestPyNumberStrOfValuesJSONLoadsNormalises(t *testing.T) {
	cases := map[string]string{"-0": "0", "1e400": "inf", "-1e400": "-inf"}
	for in, want := range cases {
		if got := PyNumberStr(json.Number(in)); got != want {
			t.Errorf("differs from Python: str(json.loads(%q)) is %q, Go gives %q", in, want, got)
		}
	}
}

func TestConfiguredCost(t *testing.T) {
	base := Prices{Input: dec("0.001"), Output: dec("0.002")}
	withCached := Prices{Input: dec("0.001"), Output: dec("0.002"), CachedInput: dec("0.0001")}
	withBoth := Prices{Input: dec("0.001"), Output: dec("0.002"), CachedInput: dec("0.0001"), CacheCreation: dec("0.00125")}
	onlyWrite := Prices{Input: dec("0.001"), Output: dec("0.002"), CacheCreation: dec("0.00125")}
	read := Usage{Prompt: 1000, Completion: 100, Total: 1100, CachedPrompt: 800}
	readWrite := Usage{Prompt: 1000, Completion: 100, Total: 1100, CachedPrompt: 700, CacheCreation: 200}
	cases := []struct {
		name string
		p    Prices
		u    Usage
		want string
	}{
		{"cached rate", withCached, read, "0.48"},
		{"no cached rate", base, read, "1.2"},
		{"read and write rates", withBoth, readWrite, "0.62"},
		{"write priced as fresh without its rate", withCached, readWrite, "0.57"},
		{"write rate without a read rate", onlyWrite, readWrite, "1.25"},
		{"writes capped by the uncached prompt", withBoth, Usage{Prompt: 100, CachedPrompt: 90, CacheCreation: 50}, "0.0215"},
		{"cached capped at prompt", withCached, Usage{Prompt: 10, CachedPrompt: 50}, "0.001"},
		{"no tokens", withBoth, Usage{}, "0"},
		{"unknown input price", Prices{Output: dec("0.002")}, read, "0"},
		{"unknown output price", Prices{Input: dec("0.001")}, read, "0"},
		{"free", Prices{Input: dec("0"), Output: dec("0")}, read, "0"},
		{"anthropic stream", Prices{Input: dec("0.000003"), Output: dec("0.000015"), CachedInput: dec("0.0000003")}, Usage{Prompt: 1000, CachedPrompt: 900, Completion: 50}, "0.00132"},
	}
	for _, tc := range cases {
		assertCost(t, tc.name, ConfiguredCost(tc.p, tc.u), tc.want)
	}
	if got := ConfiguredCost(Prices{}, read); got.Cmp(money.Zero()) != 0 {
		t.Errorf("no prices = %s", got)
	}
}
