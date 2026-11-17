package app

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"math/big"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	catalogdomain "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
)

type quoteBilling struct {
	money.ToolBilling
	lines []money.QuoteLine
	fail  bool
}

func (b *quoteBilling) Currency() money.Currency { return "RUB" }

func (b *quoteBilling) Quote(_ context.Context, lines []money.QuoteLine) ([]money.Quote, error) {
	b.lines = lines
	if b.fail {
		return nil, errors.New("billing is down")
	}
	out := make([]money.Quote, len(lines))
	for i, l := range lines {
		if l.Tool == "unsold" {
			continue
		}
		a := l.VendorCost.Mul(money.FromInt(100))
		out[i].Amount = &a
	}
	return out, nil
}

type computePricing struct{ money.USDAtProviderCost }

func (computePricing) PriceComputeHour(_ context.Context, vcpu, mem money.Decimal) (money.Decimal, error) {
	return vcpu.Add(mem), nil
}

func paidItem(t *testing.T, payers []string, hosting string) catalogdomain.Item {
	t.Helper()
	spec := `{"raw_spec":{"name":"vendor-x","metadata":{"agentarea:payers":` + mustJSON(t, payers) + `,"agentarea:cost":{
		"default":{"source":"rate","rate":{"amount":"0.5","currency":"USD"}},
		"tools":{"search":{"source":"rate","rate":{"amount":"0.2","currency":"USD"}},"unsold":{"source":"rate","rate":{"amount":"1","currency":"USD"}},"broken":{"source":"nope"}}}}}}`
	paid, proto := "paid", "mcp"
	it := catalogdomain.Item{ID: "item-1", Name: "X", Spec: json.RawMessage(spec), Pricing: &paid, Protocol: &proto}
	if hosting != "" {
		it.Hosting = &hosting
	}
	return it
}

func mustJSON(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func priceOf(t *testing.T, p catalogPricing, item catalogdomain.Item) map[string]any {
	t.Helper()
	got, err := p.Price(context.Background(), []catalogdomain.Item{item})
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(mustJSON(t, got[0])), &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func quietLog() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func TestCatalogPricingQuotesThePlatformKeyAndDropsWhatBillingDoesNotSell(t *testing.T) {
	billing := &quoteBilling{}
	p := catalogPricing{billing: billing, pricing: func() money.CustomerPricing { return money.USDAtProviderCost{} }, log: quietLog()}
	got := priceOf(t, p, paidItem(t, []string{"platform"}, ""))
	if len(billing.lines) != 3 || billing.lines[0].Tool != "*" || billing.lines[1].Tool != "search" || billing.lines[0].Connector != "vendor-x" {
		t.Fatalf("quote lines %+v", billing.lines)
	}
	prices := got["prices"].([]any)
	if len(prices) != 2 {
		t.Fatalf("prices %v", prices)
	}
	first := prices[0].(map[string]any)
	if first["tool"] != nil || first["amount"] != "50.0" || first["currency"] != "RUB" || first["basis"] != "price" {
		t.Fatalf("default price %v", first)
	}
	from := got["price_from"].(map[string]any)
	if from["tool"] != "search" || from["amount"] != "20.0" {
		t.Fatalf("price_from %v", from)
	}
	if got["kind"] != "paid" || got["compute"] != nil {
		t.Fatalf("pricing %v", got)
	}
}

func TestCatalogPricingShowsTheVendorCostWhenBillingIsDown(t *testing.T) {
	p := catalogPricing{billing: &quoteBilling{fail: true}, pricing: func() money.CustomerPricing { return money.USDAtProviderCost{} }, log: quietLog()}
	prices := priceOf(t, p, paidItem(t, []string{"platform"}, ""))["prices"].([]any)
	if len(prices) != 3 {
		t.Fatalf("prices %v", prices)
	}
	for _, raw := range prices {
		pr := raw.(map[string]any)
		if pr["basis"] != "vendor_cost" || pr["unavailable"] != true || pr["currency"] != "USD" {
			t.Fatalf("price %v", pr)
		}
	}
}

func TestCatalogPricingOwnKeyIsTheVendorCostUnquoted(t *testing.T) {
	billing := &quoteBilling{}
	p := catalogPricing{billing: billing, pricing: func() money.CustomerPricing { return money.USDAtProviderCost{} }, log: quietLog()}
	got := priceOf(t, p, paidItem(t, []string{"workspace"}, ""))
	if billing.lines != nil || len(got["prices"].([]any)) != 3 {
		t.Fatalf("quoted %v, pricing %v", billing.lines, got)
	}
}

func TestCatalogPricingEstimatesTheHostedInstanceHour(t *testing.T) {
	clock := time.Unix(0, 0)
	calls := 0
	reader := &reservationReader{log: quietLog(), now: func() time.Time { return clock },
		read: func(context.Context) (workload.Reservation, error) {
			calls++
			return workload.Reservation{CPUMillicores: 500, MemoryBytes: 512 << 20}, nil
		}}
	p := catalogPricing{pricing: func() money.CustomerPricing { return computePricing{} }, reservation: reader, log: quietLog()}
	compute := priceOf(t, p, paidItem(t, []string{"workspace"}, "agentarea"))["compute"].(map[string]any)
	if compute["vcpu"] != "0.5" || compute["memory_gib"] != "0.5" || compute["hourly"] != "1.0" || compute["currency"] != "USD" {
		t.Fatalf("compute %v", compute)
	}
	priceOf(t, p, paidItem(t, []string{"workspace"}, "agentarea"))
	if calls != 1 {
		t.Fatalf("reservation read %d times within its TTL", calls)
	}
}

func TestExactQuotientDividesLikePythonDecimal(t *testing.T) {
	for _, c := range []struct {
		n          int64
		tens, twos int
		want       string
	}{
		{1000, 3, 0, "1"}, {2500, 3, 0, "2.5"}, {250, 3, 0, "0.25"},
		{1 << 30, 0, 30, "1"}, {3 << 29, 0, 30, "1.5"}, {1 << 20, 0, 30, "0.0009765625"},
	} {
		if got := exactQuotient(big.NewInt(c.n), c.tens, c.twos).String(); got != c.want {
			t.Errorf("%d / 10^%d·2^%d = %s, want %s", c.n, c.tens, c.twos, got, c.want)
		}
	}
}
