package api

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
)

func TestQuantizeIsHalfUp(t *testing.T) {
	for in, want := range map[string]string{
		"0": "0.000000", "5": "5.000000", "0.1": "0.100000", "0.0000005": "0.000001", "0.0000004999": "0.000000",
		"1.2345675": "1.234568", "999999999999.9999995": "1000000000000.000000", "1E-30": "0.000000", "12.5E+2": "1250.000000",
	} {
		if got := Quantize6(money.MustParse(in)).Plain(); got != want {
			t.Errorf("Quantize6(%s) = %s, want %s", in, got, want)
		}
	}
}
