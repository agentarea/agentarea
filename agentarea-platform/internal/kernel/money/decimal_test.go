package money

import (
	"encoding/json"
	"errors"
	"testing"
)

// Expected values are Python's str(Decimal(s)) and format(Decimal(s), "f").
func TestParseAndFormatMatchPython(t *testing.T) {
	cases := []struct{ in, str, plain string }{
		{"0", "0", "0"},
		{"-0", "-0", "-0"},
		{"0.00", "0.00", "0.00"},
		{"-0.00", "-0.00", "-0.00"},
		{"1", "1", "1"},
		{"1.", "1", "1"},
		{".5", "0.5", "0.5"},
		{"1.50", "1.50", "1.50"},
		{"100", "100", "100"},
		{"1e3", "1E+3", "1000"},
		{"1E+3", "1E+3", "1000"},
		{"1e-7", "1E-7", "0.0000001"},
		{"0.0000001", "1E-7", "0.0000001"},
		{"0.000001", "0.000001", "0.000001"},
		{"123.456e-10", "1.23456E-8", "0.0000000123456"},
		{"12345678901234567890.123456789", "12345678901234567890.123456789", "12345678901234567890.123456789"},
		{"-42.10", "-42.10", "-42.10"},
		{"+7", "7", "7"},
		{"00012.3400", "12.3400", "12.3400"},
		{"1.5E-6", "0.0000015", "0.0000015"},
		{"5E+2", "5E+2", "500"},
		{"0E-8", "0E-8", "0.00000000"},
		{"0E+3", "0E+3", "0"},
		{" 2.5 ", "2.5", "2.5"},
	}
	for _, c := range cases {
		d, err := Parse(c.in)
		if err != nil {
			t.Errorf("Parse(%q): %v", c.in, err)
			continue
		}
		if d.String() != c.str {
			t.Errorf("str(%q) = %q, want %q", c.in, d.String(), c.str)
		}
		if d.Plain() != c.plain {
			t.Errorf("plain(%q) = %q, want %q", c.in, d.Plain(), c.plain)
		}
	}
}

func TestParseRefuses(t *testing.T) {
	for _, in := range []string{"", ".", "e5", "1e", "1e+", "NaN", "Infinity", "1,5", "١٢", "１２", "0x10", "--1", "1.2.3", "true"} {
		if _, err := Parse(in); !errors.Is(err, ErrNotDecimal) {
			t.Errorf("Parse(%q) = %v, want ErrNotDecimal", in, err)
		}
	}
}

// Expected values are Python's default-context arithmetic (prec 28, half even).
func TestArithmeticMatchesPython(t *testing.T) {
	m := MustParse
	cases := []struct {
		name string
		got  Decimal
		want string
	}{
		{"1.10+2.205", m("1.10").Add(m("2.205")), "3.305"},
		{"0E-50+1", m("0E-50").Add(m("1")), "1.000000000000000000000000000"},
		{"1-1", m("1").Sub(m("1")), "0"},
		{"-1+-0", m("-1").Add(m("-0")), "-1"},
		{"-0+-0", m("-0").Add(m("-0")), "-0"},
		{"1.10*2", m("1.10").Mul(m("2")), "2.20"},
		{"-0*5", m("-0").Mul(m("5")), "-0"},
		{"9999999999999999999999999999+1", m("9999999999999999999999999999").Add(m("1")), "1.000000000000000000000000000E+28"},
		{"long+0", m("1.000000000000000000000000000005").Add(m("0")), "1.000000000000000000000000000"},
		{"0.1+0.2", m("0.1").Add(m("0.2")), "0.3"},
		{"2.5+tiny", m("2.5").Add(m("0.00000000000000000000000000005")), "2.500000000000000000000000000"},
		{"1-1.00", m("1").Sub(m("1.00")), "0.00"},
		{"-long", m("1.0000000000000000000000000000001").Neg(), "-1.000000000000000000000000000"},
		{"12.5*0.1", m("12.5").Mul(m("0.1")), "1.25"},
		{"3*1E+2", m("3").Mul(m("1E+2")), "3E+2"},
		{"-(-0)", m("-0").Neg(), "0"},
	}
	for _, c := range cases {
		if c.got.String() != c.want {
			t.Errorf("%s = %q, want %q", c.name, c.got.String(), c.want)
		}
	}
}

func TestCmp(t *testing.T) {
	m := MustParse
	if !m("1.50").Equal(m("1.5")) || !m("-0").Equal(m("0E-3")) || m("2").Cmp(m("10")) != -1 || m("-1").Cmp(m("-2")) != 1 {
		t.Fatal("numeric comparison wrong")
	}
	if m("-0").Sign() != 0 || m("-0.1").Sign() != -1 || FromInt(-3).String() != "-3" || Zero().String() != "0" {
		t.Fatal("sign handling wrong")
	}
}

func TestJSONRoundTrip(t *testing.T) {
	type row struct {
		Amount Decimal  `json:"amount"`
		Cap    *Decimal `json:"cap"`
	}
	var r row
	if err := json.Unmarshal([]byte(`{"amount": 1e-7, "cap": "12.50"}`), &r); err != nil {
		t.Fatal(err)
	}
	out, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != `{"amount":"1E-7","cap":"12.50"}` {
		t.Fatalf("got %s", out)
	}
	if err := json.Unmarshal([]byte(`{"amount": true}`), &r); err == nil {
		t.Fatal("bool accepted as money")
	}
}

func TestParseCurrency(t *testing.T) {
	if c, err := ParseCurrency("RUB"); err != nil || c != "RUB" {
		t.Fatal(c, err)
	}
	for _, s := range []string{"rub", "RU", "RUBL", "R1B"} {
		if _, err := ParseCurrency(s); err == nil {
			t.Errorf("ParseCurrency(%q) accepted", s)
		}
	}
}
