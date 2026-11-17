package payment

import (
	"encoding/json"
	"fmt"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// atomicToUSD is Decimal(str(raw or 0)) / 10**decimals under Python's default
// context (prec 28, ROUND_HALF_EVEN), the exponent Python's division picks
// included: Decimal("10000") / 10**6 is Decimal("0.01").
func atomicToUSD(raw any, decimals int) (money.Decimal, error) {
	if decimals < 0 {
		return money.Decimal{}, fmt.Errorf("decimals %d is negative", decimals)
	}
	text := "0"
	if pyTruthy(raw) {
		text = pyStr(raw)
	}
	d, err := money.Parse(text)
	if err != nil {
		return money.Decimal{}, fmt.Errorf("amount %q is not a number", text)
	}
	return divPow10(d, decimals)
}

func decimalParts(d money.Decimal) (neg bool, coef *big.Int, exp int64) {
	plain := d.Plain()
	neg = strings.HasPrefix(plain, "-")
	digits := strings.ReplaceAll(strings.TrimPrefix(plain, "-"), ".", "")
	coef, _ = new(big.Int).SetString(digits, 10)
	exp = int64(d.Exponent())
	if exp > 0 {
		coef.Quo(coef, new(big.Int).Exp(big.NewInt(10), big.NewInt(exp), nil))
	}
	return neg, coef, exp
}

// divPow10 is decimal.Decimal.__truediv__ by Decimal(10**decimals).
func divPow10(d money.Decimal, decimals int) (money.Decimal, error) {
	neg, coef, exp := decimalParts(d)
	divisor := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(decimals)), nil)
	var q *big.Int
	var resultExp int64
	if coef.Sign() == 0 {
		q, resultExp = new(big.Int), exp
	} else {
		shift := int64(len(divisor.String()) - len(coef.String()) + money.Precision + 1)
		resultExp = exp - shift
		num, den := new(big.Int).Set(coef), new(big.Int).Set(divisor)
		if shift >= 0 {
			num.Mul(num, new(big.Int).Exp(big.NewInt(10), big.NewInt(shift), nil))
		} else {
			den.Mul(den, new(big.Int).Exp(big.NewInt(10), big.NewInt(-shift), nil))
		}
		r := new(big.Int)
		q, r = new(big.Int).QuoRem(num, den, r)
		ten, five := big.NewInt(10), big.NewInt(5)
		if r.Sign() != 0 {
			if new(big.Int).Mod(q, five).Sign() == 0 {
				q.Add(q, big.NewInt(1))
			}
		} else {
			m := new(big.Int)
			for resultExp < exp {
				if m.Mod(q, ten).Sign() != 0 {
					break
				}
				q.Quo(q, ten)
				resultExp++
			}
		}
	}
	sign := ""
	if neg {
		sign = "-"
	}
	out, err := money.Parse(sign + q.String() + "E" + strconv.FormatInt(resultExp, 10))
	if err != nil {
		return money.Decimal{}, err
	}
	return out.Mul(money.FromInt(1)), nil
}

// decimalFromConfig reads a config amount as Decimal(str(value)).
func decimalFromConfig(v any) (money.Decimal, error) {
	switch x := v.(type) {
	case string:
		return money.Parse(x)
	case json.Number:
		return money.Parse(pyNumberText(x))
	case float64:
		return money.Parse(pyFloatRepr(x))
	case float32:
		return money.Parse(pyFloatRepr(float64(x)))
	case int:
		return money.FromInt(int64(x)), nil
	case int64:
		return money.FromInt(x), nil
	case money.Decimal:
		return x, nil
	}
	return money.Decimal{}, fmt.Errorf("%v is not an amount", v)
}

// configInt reads an integer config value (JSON number or numeric string).
func configInt(v any) (int64, error) {
	switch x := v.(type) {
	case int:
		return int64(x), nil
	case int64:
		return x, nil
	case float64:
		if x != float64(int64(x)) {
			return 0, fmt.Errorf("%v is not an integer", v)
		}
		return int64(x), nil
	case json.Number:
		return x.Int64()
	case string:
		n, ok := pyIntText(x)
		if !ok || !n.IsInt64() {
			return 0, fmt.Errorf("%q is not an integer", x)
		}
		return n.Int64(), nil
	}
	return 0, fmt.Errorf("%v is not an integer", v)
}

var isoDateTime = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2})(?::(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?(?:([+-])(\d{2})(?::?(\d{2})(?::?(\d{2}))?)?)?)?$`)

// parseISO is datetime.fromisoformat(s.replace("Z", "+00:00")) for the
// extended ISO 8601 forms; aware is false for a naive datetime.
func parseISO(s string) (t time.Time, aware bool, err error) {
	m := isoDateTime.FindStringSubmatch(strings.ReplaceAll(s, "Z", "+00:00"))
	if m == nil {
		return time.Time{}, false, fmt.Errorf("%q is not an ISO 8601 datetime", s)
	}
	num := func(i int) int {
		if m[i] == "" {
			return 0
		}
		n, _ := strconv.Atoi(m[i])
		return n
	}
	nanos := 0
	if m[7] != "" {
		frac := (m[7] + "000000")[:6]
		nanos, _ = strconv.Atoi(frac)
		nanos *= 1000
	}
	loc := time.UTC
	if m[8] != "" {
		offset := num(9)*3600 + num(10)*60 + num(11)
		if m[8] == "-" {
			offset = -offset
		}
		loc = time.FixedZone("", offset)
		aware = true
	}
	year, month, day, hour, minute, sec := num(1), num(2), num(3), num(4), num(5), num(6)
	t = time.Date(year, time.Month(month), day, hour, minute, sec, nanos, loc)
	if t.Year() != year || int(t.Month()) != month || t.Day() != day || hour > 23 || minute > 59 || sec > 59 {
		return time.Time{}, false, fmt.Errorf("%q is not a valid datetime", s)
	}
	return t, aware, nil
}
