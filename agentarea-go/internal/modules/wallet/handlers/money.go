package handlers

import (
	"fmt"
	"math"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

// ceilingDigits is the adjusted exponent of 10 ** 12, the first amount
// numeric(18, 6) cannot hold.
const ceilingDigits = 12

const ceilingText = "1000000000000"

// pyRepr is repr() of a JSON value, as _parse_money writes it into its message.
func pyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return pyStrRepr(x)
	case wirejson.Float:
		f := float64(x)
		switch {
		case math.IsNaN(f):
			return "nan"
		case math.IsInf(f, 1):
			return "inf"
		case math.IsInf(f, -1):
			return "-inf"
		}
		return wirejson.FormatFloat(f)
	case fmt.Stringer:
		return x.String()
	}
	return fmt.Sprint(v)
}

func pyStrRepr(s string) string {
	q := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		q = '"'
	}
	var b strings.Builder
	b.WriteByte(q)
	for _, r := range s {
		switch {
		case r == rune(q) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(q)
	return b.String()
}

// parseMoney is _parse_money for a JSON value: a string or number of ASCII
// decimal form, nothing else.
func parseMoney(v any) (money.Decimal, bool) {
	var text string
	switch x := v.(type) {
	case string:
		text = x
	case bool, nil:
		return money.Decimal{}, false
	case wirejson.Float:
		f := float64(x)
		if math.IsNaN(f) || math.IsInf(f, 0) {
			return money.Decimal{}, false
		}
		text = wirejson.FormatFloat(f)
	case fmt.Stringer:
		text = x.String()
	default:
		return money.Decimal{}, false
	}
	d, err := money.Parse(text)
	return d, err == nil
}

func notMoney(v any, loc ...any) httpx.FieldError {
	return httpx.ValueError(pyRepr(v)+" is not a money amount", loc...)
}

// budget reads service_budget_usd: a money amount, ge 0, lt 10 ** 12, then
// rounded to the column's six places (ROUND_HALF_UP) and refused if that
// rounds up to the ceiling. ok is false after an error was appended.
func budget(v any, loc []any, errs *[]httpx.FieldError) (money.Decimal, bool) {
	d, ok := parseMoney(v)
	if !ok {
		*errs = append(*errs, notMoney(v, loc...))
		return money.Decimal{}, false
	}
	if d.Sign() < 0 {
		*errs = append(*errs, httpx.GreaterThanEqual(0, loc...))
		return money.Decimal{}, false
	}
	if api.Adjusted(d) >= ceilingDigits {
		*errs = append(*errs, httpx.LessThan(ceilingInt, loc...))
		return money.Decimal{}, false
	}
	stored := api.Quantize6(d)
	if api.Adjusted(stored) >= ceilingDigits {
		*errs = append(*errs, httpx.ValueError("service_budget_usd must be less than "+ceilingText, loc...))
		return money.Decimal{}, false
	}
	return stored, true
}

const ceilingInt = int64(1_000_000_000_000)

// nonNegative reads session_budget_usd: a money amount, ge 0.
func nonNegative(v any, loc []any, errs *[]httpx.FieldError) (money.Decimal, bool) {
	d, ok := parseMoney(v)
	if !ok {
		*errs = append(*errs, notMoney(v, loc...))
		return money.Decimal{}, false
	}
	if d.Sign() < 0 {
		*errs = append(*errs, httpx.GreaterThanEqual(0, loc...))
		return money.Decimal{}, false
	}
	return d, true
}
