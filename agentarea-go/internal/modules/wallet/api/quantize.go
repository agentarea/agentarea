package api

import (
	"math/big"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

// Quantize6 is d.quantize(Decimal("0.000001"), ROUND_HALF_UP) for a
// non-negative d below the ceiling.
func Quantize6(d money.Decimal) money.Decimal {
	if d.IsZero() || Adjusted(d) < -7 {
		return money.MustParse("0.000000")
	}
	plain := d.Plain()
	whole, frac, _ := strings.Cut(plain, ".")
	frac += strings.Repeat("0", 7)
	digits := whole + frac[:6]
	up := frac[6] >= '5'
	n, _ := new(big.Int).SetString(digits, 10)
	if up {
		n.Add(n, big.NewInt(1))
	}
	s := n.String()
	for len(s) < 7 {
		s = "0" + s
	}
	return money.MustParse(s[:len(s)-6] + "." + s[len(s)-6:])
}
