package app

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	catalogdomain "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	catalogservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/service"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/runtime/workload"
	runsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

// catalogConnections renders connections' catalog lookup as the catalog card shows it.
type catalogConnections struct {
	x connectionsapi.CatalogConnections
}

var _ catalogservice.CatalogConnections = catalogConnections{}

func (c catalogConnections) Of(ctx context.Context, caller authn.Caller, itemIDs []string) (map[string][]any, error) {
	got, err := c.x.CatalogConnections(ctx, caller, itemIDs)
	if err != nil {
		return nil, err
	}
	out := make(map[string][]any, len(got))
	for item, conns := range got {
		list := make([]any, len(conns))
		for i, conn := range conns {
			list[i] = wirejson.Object{{Key: "id", Value: conn.ID}, {Key: "kind", Value: conn.Kind}, {Key: "name", Value: conn.Name}}
		}
		out[item] = list
	}
	return out, nil
}

// catalogPricing is price_catalog_items: what using a connections catalog
// entry costs through AgentArea (ADR-0038: billing's price on the platform's
// key, else the vendor's own cost), and what a hosted entry's instance
// reserves per hour.
type catalogPricing struct {
	billing     money.ToolBilling
	pricing     func() money.CustomerPricing
	reservation *reservationReader
	log         *slog.Logger
}

var _ catalogservice.CatalogPricing = catalogPricing{}

type toolPrice struct {
	tool        *string
	amount      money.Decimal
	currency    string
	unit        string
	basis       string
	unavailable bool
}

func (p toolPrice) json() wirejson.Object {
	var tool any
	if p.tool != nil {
		tool = *p.tool
	}
	return wirejson.Object{
		{Key: "tool", Value: tool}, {Key: "amount", Value: p.amount}, {Key: "currency", Value: p.currency},
		{Key: "unit", Value: p.unit}, {Key: "basis", Value: p.basis}, {Key: "unavailable", Value: p.unavailable},
	}
}

type pricedEntry struct {
	kind   string
	payers []string
	costs  []toolPrice
}

func (p catalogPricing) Price(ctx context.Context, items []catalogdomain.Item) ([]any, error) {
	found := make([]*pricedEntry, len(items))
	for i, item := range items {
		if item.Pricing == nil {
			continue
		}
		var spec catalogdomain.Mapping
		_ = json.Unmarshal(item.Spec, &spec)
		payers, err := catalogdomain.ConnectorPayers(catalogdomain.CatalogMetadata(spec)["agentarea:payers"])
		if err != nil {
			p.log.WarnContext(ctx, "Catalog entry declares malformed payers", "item_id", item.ID, "error", err)
			continue
		}
		e := &pricedEntry{kind: *item.Pricing, payers: payers}
		if e.kind == "paid" {
			e.costs = p.vendorCosts(ctx, item, spec)
		}
		found[i] = e
	}
	type line struct {
		index     int
		connector string
		cost      toolPrice
	}
	var onPlatform []line
	for i, e := range found {
		if e != nil && hasPayer(e.payers, "platform") {
			for _, cost := range e.costs {
				onPlatform = append(onPlatform, line{i, connector(items[i]), cost})
			}
		}
	}
	costs := make([]toolPrice, len(onPlatform))
	connectors := make([]string, len(onPlatform))
	for i, l := range onPlatform {
		costs[i], connectors[i] = l.cost, l.connector
	}
	priced := p.billingPrices(ctx, connectors, costs)
	byItem := map[int][]toolPrice{}
	for i, l := range onPlatform {
		if priced[i] != nil {
			byItem[l.index] = append(byItem[l.index], *priced[i])
		}
	}
	out := make([]any, len(items))
	for i, e := range found {
		if e == nil {
			continue
		}
		prices := e.costs
		if hasPayer(e.payers, "platform") {
			prices = byItem[i]
		}
		rendered := make([]any, len(prices))
		for j, price := range prices {
			rendered[j] = price.json()
		}
		var from any
		if len(prices) > 0 {
			from = prices[indexOfMin(prices)].json()
		}
		compute, err := p.computeEstimate(ctx, items[i])
		if err != nil {
			return nil, err
		}
		out[i] = wirejson.Object{
			{Key: "kind", Value: e.kind}, {Key: "payers", Value: e.payers},
			{Key: "price_from", Value: from}, {Key: "prices", Value: rendered}, {Key: "compute", Value: compute},
		}
	}
	return out, nil
}

// indexOfMin is min(prices, key=amount): the first of the cheapest.
func indexOfMin(prices []toolPrice) int {
	best := 0
	for i, p := range prices {
		if p.amount.Cmp(prices[best].amount) < 0 {
			best = i
		}
	}
	return best
}

func hasPayer(payers []string, want string) bool {
	for _, p := range payers {
		if p == want {
			return true
		}
	}
	return false
}

// connector is the id billing prices the entry's calls by, as metering names it.
func connector(item catalogdomain.Item) string {
	if item.Protocol != nil && *item.Protocol == "api" {
		return item.ExternalID
	}
	var spec catalogdomain.Mapping
	_ = json.Unmarshal(item.Spec, &spec)
	if name, ok := catalogdomain.AsMapping(spec["raw_spec"])["name"]; ok && name != nil && name != "" && name != false {
		return fmt.Sprint(name)
	}
	return item.Name
}

// vendorCosts are the per-unit rates the entry declares: the default first,
// then each tool's in the stored order. A malformed declaration is skipped.
func (p catalogPricing) vendorCosts(ctx context.Context, item catalogdomain.Item, spec catalogdomain.Mapping) []toolPrice {
	cost := catalogdomain.AsMapping(catalogdomain.CatalogMetadata(spec)["agentarea:cost"])
	type decl struct {
		tool *string
		raw  any
	}
	decls := []decl{{nil, cost["default"]}}
	tools := catalogdomain.AsMapping(cost["tools"])
	for _, name := range toolCostOrder(item.Spec, tools) {
		decls = append(decls, decl{&name, tools[name]})
	}
	var out []toolPrice
	for _, d := range decls {
		if d.raw == nil {
			continue
		}
		rate, currency, unit, err := runsservice.DeclaredRate(d.raw)
		if err != nil {
			tool := "<default>"
			if d.tool != nil {
				tool = *d.tool
			}
			p.log.WarnContext(ctx, "Catalog entry declares a malformed cost", "connector", connector(item), "tool", tool, "error", err)
			continue
		}
		if rate == nil {
			continue
		}
		out = append(out, toolPrice{tool: d.tool, amount: *rate, currency: currency, unit: unit, basis: "vendor_cost"})
	}
	return out
}

// toolCostOrder is the keys of agentarea:cost.tools in the order the spec stores them.
func toolCostOrder(raw json.RawMessage, tools catalogdomain.Mapping) []string {
	var doc struct {
		RawSpec struct {
			Metadata map[string]json.RawMessage `json:"metadata"`
		} `json:"raw_spec"`
	}
	var cost struct {
		Tools json.RawMessage `json:"tools"`
	}
	if json.Unmarshal(raw, &doc) != nil || json.Unmarshal(doc.RawSpec.Metadata["agentarea:cost"], &cost) != nil {
		return nil
	}
	dec := json.NewDecoder(bytes.NewReader(cost.Tools))
	if t, err := dec.Token(); err != nil || t != json.Delim('{') {
		return nil
	}
	var keys []string
	for dec.More() {
		t, err := dec.Token()
		if err != nil {
			return keys
		}
		k, _ := t.(string)
		if _, ok := tools[k]; ok {
			keys = append(keys, k)
		}
		var skip json.RawMessage
		if dec.Decode(&skip) != nil {
			return keys
		}
	}
	return keys
}

// billingPrices are the costs as billing prices them on the platform's key,
// in one quote; nil for a tool billing does not sell on our key. Billing
// down, the vendor cost stands in, marked unavailable.
func (p catalogPricing) billingPrices(ctx context.Context, connectors []string, costs []toolPrice) []*toolPrice {
	out := make([]*toolPrice, len(costs))
	if p.billing == nil || len(costs) == 0 {
		for i := range costs {
			out[i] = &costs[i]
		}
		return out
	}
	lines := make([]money.QuoteLine, len(costs))
	for i, c := range costs {
		tool := "*"
		if c.tool != nil {
			tool = *c.tool
		}
		lines[i] = money.QuoteLine{Payer: "platform", Connector: connectors[i], Tool: tool, VendorCost: c.amount, VendorCurrency: money.Currency(c.currency)}
	}
	quotes, err := p.billing.Quote(ctx, lines)
	if err == nil && len(quotes) != len(lines) {
		err = fmt.Errorf("billing answered %d quotes for %d lines", len(quotes), len(lines))
	}
	if err != nil {
		p.log.ErrorContext(ctx, "Billing could not quote catalog prices", "lines", len(lines), "error", err)
		for i := range costs {
			c := costs[i]
			c.unavailable = true
			out[i] = &c
		}
		return out
	}
	for i, q := range quotes {
		if q.Amount == nil {
			continue
		}
		c := costs[i]
		c.amount, c.currency, c.basis = *q.Amount, string(p.billing.Currency()), "price"
		out[i] = &c
	}
	return out
}

// computeEstimate is what a hosted entry's running instance reserves and
// what an hour of it costs; nil for an entry that does not run on
// AgentArea or while the reservation is unknown.
func (p catalogPricing) computeEstimate(ctx context.Context, item catalogdomain.Item) (any, error) {
	if item.Hosting == nil || *item.Hosting != "agentarea" || p.reservation == nil {
		return nil, nil
	}
	r, ok := p.reservation.get(ctx)
	if !ok {
		return nil, nil
	}
	var hourly, currency any
	if cp, isCompute := p.pricing().(money.ComputePricing); isCompute {
		amount, err := cp.PriceComputeHour(ctx, r.vcpu, r.memoryGiB)
		switch {
		case errors.Is(err, money.ErrComputeUnpriced):
		case err != nil:
			return nil, err
		default:
			hourly, currency = amount, string(cp.Currency())
		}
	}
	return wirejson.Object{{Key: "vcpu", Value: r.vcpu}, {Key: "memory_gib", Value: r.memoryGiB}, {Key: "hourly", Value: hourly}, {Key: "currency", Value: currency}}, nil
}

type instanceReservation struct{ vcpu, memoryGiB money.Decimal }

// reservationReader is instance_reservation: what a new hosted MCP instance
// reserves, re-read at most once per TTL, nil while it is unknown.
type reservationReader struct {
	read func(context.Context) (workload.Reservation, error)
	log  *slog.Logger
	now  func() time.Time

	mu    sync.Mutex
	value *instanceReservation
	next  time.Time
}

const (
	reservationTTL        = 5 * time.Minute
	reservationRetryAfter = 30 * time.Second
)

func (r *reservationReader) get(ctx context.Context) (instanceReservation, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.now().Before(r.next) {
		if r.value == nil {
			return instanceReservation{}, false
		}
		return *r.value, true
	}
	got, err := r.read(ctx)
	if err == nil && (got.CPUMillicores < 0 || got.MemoryBytes < 0) {
		err = fmt.Errorf("reservation is not a pair of non-negative integers: %+v", got)
	}
	if err != nil {
		r.log.WarnContext(ctx, "MCP runtime did not report an instance reservation", "error", err)
		r.value, r.next = nil, r.now().Add(reservationRetryAfter)
		return instanceReservation{}, false
	}
	r.next = r.now().Add(reservationTTL)
	if got.CPUMillicores == 0 && got.MemoryBytes == 0 {
		r.value = nil
		return instanceReservation{}, false
	}
	r.value = &instanceReservation{vcpu: exactQuotient(big.NewInt(got.CPUMillicores), 3, 0), memoryGiB: exactQuotient(big.NewInt(got.MemoryBytes), 0, 30)}
	return *r.value, true
}

// exactQuotient is n / (10^tens × 2^twos) as Python's Decimal divides when
// the result is exact: trailing zeros dropped down to exponent 0.
func exactQuotient(n *big.Int, tens, twos int) money.Decimal {
	coef := new(big.Int).Mul(n, new(big.Int).Exp(big.NewInt(5), big.NewInt(int64(twos)), nil))
	exp := tens + twos
	ten := big.NewInt(10)
	for exp > 0 {
		q, rem := new(big.Int).QuoRem(coef, ten, new(big.Int))
		if rem.Sign() != 0 {
			break
		}
		coef, exp = q, exp-1
	}
	digits := coef.String()
	if exp > 0 {
		if len(digits) <= exp {
			digits = strings.Repeat("0", exp-len(digits)+1) + digits
		}
		digits = digits[:len(digits)-exp] + "." + digits[len(digits)-exp:]
	}
	return money.MustParse(digits)
}
