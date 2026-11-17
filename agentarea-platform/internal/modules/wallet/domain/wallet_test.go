package domain

import (
	"errors"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
)

// Cases are test_wallet_service.py's _validate_config tests.
func TestValidateConfig(t *testing.T) {
	for name, c := range map[string]struct {
		typ        string
		x402, mpp  bool
		wantDetail string
	}{
		"x402 with its config": {api.TypeX402, true, false, ""},
		"x402 without":         {api.TypeX402, false, true, "x402_config is required for wallet_type 'x402'"},
		"mpp with its config":  {api.TypeMPP, false, true, ""},
		"mpp without":          {api.TypeMPP, true, false, "mpp_config is required for wallet_type 'mpp'"},
		"dual with both":       {api.TypeDual, true, true, ""},
		"dual without x402":    {api.TypeDual, false, true, "x402_config is required for wallet_type 'dual'"},
		"dual without mpp":     {api.TypeDual, true, false, "mpp_config is required for wallet_type 'dual'"},
		"dual with neither":    {api.TypeDual, false, false, "x402_config is required for wallet_type 'dual'"},
	} {
		err := ValidateConfig(c.typ, c.x402, c.mpp)
		var ce *ConfigError
		switch {
		case c.wantDetail == "" && err != nil:
			t.Errorf("%s: %v", name, err)
		case c.wantDetail != "" && (!errors.As(err, &ce) || ce.Message != c.wantDetail):
			t.Errorf("%s: %v, want %q", name, err, c.wantDetail)
		}
	}
}

func TestEnumValues(t *testing.T) {
	for _, c := range []struct {
		allowed []string
		want    []string
	}{
		{WalletTypes(), []string{"x402", "mpp", "dual"}},
		{BudgetPeriods(), []string{"execution", "daily", "monthly"}},
		{Statuses(), []string{"active", "disabled"}},
	} {
		if len(c.allowed) != len(c.want) {
			t.Fatalf("%v, want %v", c.allowed, c.want)
		}
		for i := range c.want {
			if c.allowed[i] != c.want[i] {
				t.Errorf("%v, want %v", c.allowed, c.want)
			}
		}
	}
	if Valid(BudgetPeriods(), "weekly") || !Valid(BudgetPeriods(), "daily") {
		t.Error("weekly is not a period")
	}
}

func TestPeriodStartIsUTC(t *testing.T) {
	zone := time.FixedZone("UTC+9", 9*3600)
	now := time.Date(2026, 11, 12, 5, 30, 0, 0, zone) // 2026-11-11 20:30 UTC
	day, ok := PeriodStart(api.PeriodDaily, now)
	if !ok || !day.Equal(time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("daily %v %v", day, ok)
	}
	month, ok := PeriodStart(api.PeriodMonthly, now)
	if !ok || !month.Equal(time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("monthly %v %v", month, ok)
	}
	if _, ok := PeriodStart(api.PeriodExecution, now); ok {
		t.Error("execution has no window")
	}
	if _, ok := PeriodStart("weekly", now); ok {
		t.Error("an unknown period has no window")
	}
}
