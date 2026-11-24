// Package money is the decimal type every amount and metered quantity uses,
// the deployment currency, and the billing ports the open core asks
// (tool billing, customer pricing, account balance, workspace usage).
//
// Decimal reads and writes the strings Python's decimal.Decimal does
// (agentarea_common/money.py): amounts cross Temporal payloads, events,
// task_events rows and API bodies as strings, and a mixed Python/Go fleet must
// write the same bytes (decision 11).
package money

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
)

// Precision is the significant digits of an arithmetic result, as Python's
// default decimal context (prec=28, ROUND_HALF_EVEN). Parsing is exact.
const Precision = 28

// Decimal is an exact decimal number: coef × 10^exp with a sign. The zero
// value is 0. Values are immutable.
type Decimal struct {
	coef *big.Int // absolute value; nil means 0
	exp  int32
	neg  bool
}

// ErrNotDecimal is returned for text that is not an ASCII decimal number.
var ErrNotDecimal = errors.New("not a money amount")

// Parse reads [+-]digits[.digits][e[+-]digits] after trimming whitespace.
// Only ASCII digits are accepted: Python's Decimal also reads every Unicode
// digit, which money.py refuses, and so does Parse. NaN and Infinity are
// refused.
func Parse(s string) (Decimal, error) {
	text := strings.TrimSpace(s)
	fail := func() (Decimal, error) { return Decimal{}, fmt.Errorf("%q: %w", s, ErrNotDecimal) }
	i := 0
	neg := false
	if i < len(text) && (text[i] == '+' || text[i] == '-') {
		neg = text[i] == '-'
		i++
	}
	var digits strings.Builder
	intStart := i
	for i < len(text) && isDigit(text[i]) {
		digits.WriteByte(text[i])
		i++
	}
	intDigits := i - intStart
	fracDigits := 0
	if i < len(text) && text[i] == '.' {
		i++
		fracStart := i
		for i < len(text) && isDigit(text[i]) {
			digits.WriteByte(text[i])
			i++
		}
		fracDigits = i - fracStart
	}
	if intDigits == 0 && fracDigits == 0 {
		return fail()
	}
	exp := int64(-fracDigits)
	if i < len(text) && (text[i] == 'e' || text[i] == 'E') {
		i++
		expStart := i
		if i < len(text) && (text[i] == '+' || text[i] == '-') {
			i++
		}
		digitStart := i
		for i < len(text) && isDigit(text[i]) {
			i++
		}
		if i == digitStart {
			return fail()
		}
		e, err := strconv.ParseInt(text[expStart:i], 10, 32)
		if err != nil {
			return fail()
		}
		exp += e
	}
	if i != len(text) || exp < math.MinInt32 || exp > math.MaxInt32 {
		return fail()
	}
	coef, ok := new(big.Int).SetString(digits.String(), 10)
	if !ok {
		return fail()
	}
	return Decimal{coef: coef, exp: int32(exp), neg: neg}, nil
}

// MustParse is Parse for constants and tests; it panics on bad input.
func MustParse(s string) Decimal {
	d, err := Parse(s)
	if err != nil {
		panic(err)
	}
	return d
}

// FromInt returns n with exponent 0.
func FromInt(n int64) Decimal {
	c := big.NewInt(n)
	neg := c.Sign() < 0
	return Decimal{coef: c.Abs(c), neg: neg}
}

// Zero is 0 with exponent 0.
func Zero() Decimal { return Decimal{} }

func (d Decimal) abs() *big.Int {
	if d.coef == nil {
		return new(big.Int)
	}
	return d.coef
}

func (d Decimal) signed() *big.Int {
	v := new(big.Int).Set(d.abs())
	if d.neg {
		v.Neg(v)
	}
	return v
}

// IsZero reports whether d is numerically zero (0, -0, 0.00, 0E-8).
func (d Decimal) IsZero() bool { return d.abs().Sign() == 0 }

// Sign is -1, 0 or +1; negative zero is 0.
func (d Decimal) Sign() int {
	if d.IsZero() {
		return 0
	}
	if d.neg {
		return -1
	}
	return 1
}

// Exponent is the power of ten of the last digit (-2 for 1.50).
func (d Decimal) Exponent() int32 { return d.exp }

// Cmp compares numerically: 1.50 equals 1.5, -0 equals 0.
func (d Decimal) Cmp(o Decimal) int {
	a, b := d.signed(), o.signed()
	e := min(d.exp, o.exp)
	a.Mul(a, pow10(int64(d.exp)-int64(e)))
	b.Mul(b, pow10(int64(o.exp)-int64(e)))
	return a.Cmp(b)
}

// Equal is Cmp == 0.
func (d Decimal) Equal(o Decimal) bool { return d.Cmp(o) == 0 }

// Neg is Python's unary minus: -0 becomes 0, as the default context does.
func (d Decimal) Neg() Decimal {
	if d.IsZero() {
		return Decimal{coef: d.coef, exp: d.exp}.round()
	}
	return Decimal{coef: d.coef, exp: d.exp, neg: !d.neg}.round()
}

// Abs drops the sign, rounded to Precision digits as Python's abs() is.
func (d Decimal) Abs() Decimal { return Decimal{coef: d.coef, exp: d.exp}.round() }

// Add returns d + o, rounded to Precision digits as Python does.
func (d Decimal) Add(o Decimal) Decimal {
	exp := min(d.exp, o.exp)
	switch {
	case d.IsZero() && o.IsZero():
		return Decimal{coef: new(big.Int), exp: exp, neg: d.neg && o.neg}
	case d.IsZero():
		return o.rescaleDown(max(int64(exp), int64(o.exp)-Precision-1)).round()
	case o.IsZero():
		return d.rescaleDown(max(int64(exp), int64(d.exp)-Precision-1)).round()
	}
	a := d.signed()
	a.Mul(a, pow10(int64(d.exp)-int64(exp)))
	b := o.signed()
	b.Mul(b, pow10(int64(o.exp)-int64(exp)))
	sum := a.Add(a, b)
	neg := sum.Sign() < 0
	return Decimal{coef: sum.Abs(sum), exp: exp, neg: neg}.round()
}

// Sub returns d - o (Python: d + o.copy_negate()).
func (d Decimal) Sub(o Decimal) Decimal {
	return d.Add(Decimal{coef: o.coef, exp: o.exp, neg: !o.neg})
}

// Mul returns d × o, rounded to Precision digits as Python does.
func (d Decimal) Mul(o Decimal) Decimal {
	exp := int64(d.exp) + int64(o.exp)
	p := new(big.Int).Mul(d.abs(), o.abs())
	return Decimal{coef: p, exp: clampExp(exp), neg: d.neg != o.neg}.round()
}

// String is Python's str(Decimal): scientific notation when the exponent is
// positive or the number is smaller than 1E-6 ("1E+3", "1E-7", "0.000001").
func (d Decimal) String() string {
	digits := d.abs().String()
	sign := ""
	if d.neg {
		sign = "-"
	}
	exp := int64(d.exp)
	leftDigits := exp + int64(len(digits))
	dotPlace := int64(1)
	if exp <= 0 && leftDigits > -6 {
		dotPlace = leftDigits
	}
	var intPart, fracPart string
	switch {
	case dotPlace <= 0:
		intPart = "0"
		fracPart = "." + strings.Repeat("0", int(-dotPlace)) + digits
	case dotPlace >= int64(len(digits)):
		intPart = digits + strings.Repeat("0", int(dotPlace-int64(len(digits))))
	default:
		intPart = digits[:dotPlace]
		fracPart = "." + digits[dotPlace:]
	}
	expPart := ""
	if leftDigits != dotPlace {
		expPart = fmt.Sprintf("E%+d", leftDigits-dotPlace)
	}
	return sign + intPart + fracPart + expPart
}

// Plain is format(d, "f"): never an exponent ("1000" for 1E+3, "0.0000001"
// for 1E-7). This is what Postgres NUMERIC prints.
func (d Decimal) Plain() string {
	digits := d.abs().String()
	sign := ""
	if d.neg {
		sign = "-"
	}
	if d.exp >= 0 {
		if d.IsZero() {
			return sign + "0"
		}
		return sign + digits + strings.Repeat("0", int(d.exp))
	}
	frac := int(-d.exp)
	if len(digits) <= frac {
		return sign + "0." + strings.Repeat("0", frac-len(digits)) + digits
	}
	return sign + digits[:len(digits)-frac] + "." + digits[len(digits)-frac:]
}

// MarshalJSON writes the Python string form, quoted: Money serializes to str.
func (d Decimal) MarshalJSON() ([]byte, error) { return json.Marshal(d.String()) }

// UnmarshalJSON reads a JSON string or number; null leaves d unchanged.
func (d *Decimal) UnmarshalJSON(b []byte) error {
	text := strings.TrimSpace(string(b))
	if text == "null" {
		return nil
	}
	if strings.HasPrefix(text, `"`) {
		if err := json.Unmarshal(b, &text); err != nil {
			return err
		}
	}
	v, err := Parse(text)
	if err != nil {
		return err
	}
	*d = v
	return nil
}

// MarshalText writes the Python string form.
func (d Decimal) MarshalText() ([]byte, error) { return []byte(d.String()), nil }

// UnmarshalText parses like Parse.
func (d *Decimal) UnmarshalText(b []byte) error {
	v, err := Parse(string(b))
	if err != nil {
		return err
	}
	*d = v
	return nil
}

// rescaleDown lowers the exponent to exp (exact; exp <= d.exp).
func (d Decimal) rescaleDown(exp int64) Decimal {
	c := new(big.Int).Mul(d.abs(), pow10(int64(d.exp)-exp))
	return Decimal{coef: c, exp: clampExp(exp), neg: d.neg}
}

// round keeps Precision significant digits, ROUND_HALF_EVEN.
func (d Decimal) round() Decimal {
	digits := len(d.abs().String())
	if digits <= Precision {
		return d
	}
	drop := int64(digits - Precision)
	div := pow10(drop)
	q, r := new(big.Int).QuoRem(d.abs(), div, new(big.Int))
	half := new(big.Int).Rsh(div, 1)
	if c := r.Cmp(half); c > 0 || (c == 0 && q.Bit(0) == 1) {
		q.Add(q, big.NewInt(1))
	}
	if len(q.String()) > Precision {
		q.Quo(q, big.NewInt(10))
		drop++
	}
	return Decimal{coef: q, exp: clampExp(int64(d.exp) + drop), neg: d.neg}
}

func pow10(n int64) *big.Int {
	return new(big.Int).Exp(big.NewInt(10), big.NewInt(n), nil)
}

func clampExp(e int64) int32 {
	if e > math.MaxInt32 || e < math.MinInt32 {
		panic(fmt.Sprintf("money: exponent %d out of range", e))
	}
	return int32(e)
}

func isDigit(c byte) bool { return c >= '0' && c <= '9' }
