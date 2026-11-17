package service

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// A tool call's cost as its connector declares it (tool_cost.py).

const (
	sourceFree    = "free"
	sourceSettled = "settled"
	sourceUnknown = "unknown"
)

var (
	currencyRe = regexp.MustCompile(`^[A-Z]{3}$`)
	pathRe     = regexp.MustCompile(`^\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])*$`)
	pathStepRe = regexp.MustCompile(`^(?:\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\])`)
	urlParamRe = regexp.MustCompile(`\{([A-Za-z_][A-Za-z0-9_]*)\}`)
)

// errToolCost: a declaration is malformed, or a call cannot be metered by it.
var errToolCost = errors.New("tool cost")

func costErr(format string, a ...any) error {
	return fmt.Errorf("%w: %s", errToolCost, fmt.Sprintf(format, a...))
}

func costReason(err error) string {
	return strings.TrimPrefix(err.Error(), errToolCost.Error()+": ")
}

// quantity is how many units one call used: a constant, an argument, or read from the response.
type quantity struct {
	constant    *money.Decimal
	arg         string
	argDefault  *money.Decimal
	count, path string
}

type valueRef struct{ path, meta string }

type settleParam struct {
	name string
	ref  valueRef
}

type costModel struct {
	source           string
	unit             string
	rate             *money.Decimal
	currency         string
	qty              quantity
	reportedPath     string
	reportedMeta     string
	exact            bool
	estimate         *money.Decimal
	estimateCurrency string
	settleParams     []settleParam
	settle           *settleFetch
}

// settleFetch is where a settled cost is read later (settled.fetch).
type settleFetch struct {
	url, costPath, donePath string
	doneIn                  []string
}

// meteredCost is what one call cost the payer, as the vendor charged it.
type meteredCost struct {
	quantity     money.Decimal
	unit         string
	vendorCost   money.Decimal
	currency     string
	source       string
	exact        bool
	settleParams map[string]string
}

// costModelOf is the binding's declared cost: its declaration, else its flat price per call.
func costModelOf(c *api.ToolCost) (costModel, error) {
	if c.Declaration != nil {
		return parseCostModel(c.Declaration)
	}
	one, rate := money.FromInt(1), c.VendorCost
	return costModel{source: sourceRate, unit: unitOf(c), rate: &rate, currency: c.VendorCurrency, qty: quantity{constant: &one}}, nil
}

func jsonPath(doc any, path string) (any, bool) {
	if !strings.HasPrefix(path, "$") {
		return nil, false
	}
	rest, node := path[1:], doc
	for rest != "" {
		m := pathStepRe.FindStringSubmatch(rest)
		if m == nil {
			return nil, false
		}
		if m[1] != "" {
			obj, ok := node.(map[string]any)
			if !ok {
				return nil, false
			}
			if node, ok = obj[m[1]]; !ok {
				return nil, false
			}
		} else {
			list, ok := node.([]any)
			i, _ := strconv.Atoi(m[2])
			if !ok || i >= len(list) {
				return nil, false
			}
			node = list[i]
		}
		rest = rest[len(m[0]):]
	}
	return node, true
}

func readPath(body any, path string) (any, error) {
	v, ok := jsonPath(body, path)
	if !ok {
		return nil, costErr("the response carries no %s", path)
	}
	return v, nil
}

func validPath(v any, where string) (string, error) {
	s, ok := v.(string)
	if !ok || !pathRe.MatchString(s) {
		return "", costErr("%s must be a path like $.field, got %s", where, pyRepr(v))
	}
	return s, nil
}

func costDecimal(v any, where string) (money.Decimal, error) {
	var s string
	switch x := v.(type) {
	case bool, nil:
		return money.Decimal{}, costErr("%s must be a number", where)
	case string:
		s = strings.TrimSpace(x)
	case float64:
		s = strconv.FormatFloat(x, 'f', -1, 64)
	case int:
		s = strconv.Itoa(x)
	case int64:
		s = strconv.FormatInt(x, 10)
	case money.Decimal:
		s = x.String()
	default:
		s = fmt.Sprint(x)
	}
	d, err := money.Parse(s)
	if err != nil {
		return money.Decimal{}, costErr("%s must be a number, got %s", where, pyRepr(v))
	}
	if d.Sign() < 0 {
		return money.Decimal{}, costErr("%s must be a non-negative number, got %s", where, pyRepr(v))
	}
	return d, nil
}

func costCurrency(v any, where string) (string, error) {
	s, ok := v.(string)
	if ok && s == "USDC" {
		s = "USD"
	}
	if !ok || !currencyRe.MatchString(s) {
		return "", costErr("%s must be an ISO 4217 code like RUB, got %s", where, pyRepr(v))
	}
	return s, nil
}

func pyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return "'" + x + "'"
	case bool:
		if x {
			return "True"
		}
		return "False"
	}
	return fmt.Sprint(v)
}

func parseQuantity(raw any) (quantity, error) {
	one := money.FromInt(1)
	if raw == nil {
		return quantity{constant: &one}, nil
	}
	m, ok := raw.(map[string]any)
	if !ok {
		d, err := costDecimal(raw, "rate.quantity")
		return quantity{constant: &d}, err
	}
	kinds := 0
	for k := range m {
		switch k {
		case "arg", "count", "path":
			kinds++
		case "default":
		default:
			kinds = 99
		}
	}
	if kinds != 1 {
		return quantity{}, costErr("rate.quantity must be one of arg, count, path; got %v", m)
	}
	if a, has := m["arg"]; has {
		name, ok := a.(string)
		if !ok || name == "" {
			return quantity{}, costErr("rate.quantity.arg must name an argument")
		}
		q := quantity{arg: name}
		if d, has := m["default"]; has && d != nil {
			v, err := costDecimal(d, "rate.quantity.default")
			if err != nil {
				return quantity{}, err
			}
			q.argDefault = &v
		}
		return q, nil
	}
	if _, has := m["default"]; has {
		return quantity{}, costErr("rate.quantity.default applies only to arg")
	}
	if c, has := m["count"]; has {
		p, err := validPath(c, "rate.quantity.count")
		return quantity{count: p}, err
	}
	p, err := validPath(m["path"], "rate.quantity.path")
	return quantity{path: p}, err
}

func (q quantity) evaluate(args map[string]any, body any) (money.Decimal, error) {
	switch {
	case q.arg != "":
		if v, ok := args[q.arg]; ok && v != nil {
			return costDecimal(v, "argument "+q.arg)
		}
		if q.argDefault == nil {
			return money.Decimal{}, costErr("argument %s is missing and declares no default", q.arg)
		}
		return *q.argDefault, nil
	case q.count != "":
		items, err := readPath(body, q.count)
		if err != nil {
			return money.Decimal{}, err
		}
		list, ok := items.([]any)
		if !ok {
			return money.Decimal{}, costErr("%s in the response is not a list", q.count)
		}
		return money.FromInt(int64(len(list))), nil
	case q.path != "":
		v, err := readPath(body, q.path)
		if err != nil {
			return money.Decimal{}, err
		}
		return costDecimal(v, q.path)
	case q.constant != nil:
		return *q.constant, nil
	}
	return money.Decimal{}, costErr("rate.quantity is not declared")
}

// parseCostModel is parse_cost_model; nil is an unknown cost.
func parseCostModel(raw map[string]any) (costModel, error) {
	if raw == nil {
		return costModel{source: sourceUnknown, unit: "call"}, nil
	}
	source, _ := raw["source"].(string)
	switch source {
	case sourceFree, sourceRate, sourceReport, sourceSettled, sourceUnknown:
	default:
		return costModel{}, costErr("unknown cost source %s", pyRepr(raw["source"]))
	}
	m := costModel{source: source, unit: "call", exact: source == sourceReport || source == sourceSettled}
	if u, has := raw["unit"]; has && u != nil && u != "" {
		s, ok := u.(string)
		if !ok {
			return costModel{}, costErr("unit must be a string")
		}
		m.unit = s
	}
	if e, has := raw["exact"]; has {
		b, ok := e.(bool)
		if !ok {
			return costModel{}, costErr("exact must be true or false")
		}
		m.exact = b
	}
	if est, has := raw["estimate"]; has && est != nil {
		e, ok := est.(map[string]any)
		if !ok {
			return costModel{}, costErr("estimate declares {amount, currency}")
		}
		amount, err := costDecimal(e["amount"], "estimate.amount")
		if err != nil {
			return costModel{}, err
		}
		if m.estimateCurrency, err = costCurrency(e["currency"], "estimate.currency"); err != nil {
			return costModel{}, err
		}
		m.estimate = &amount
	}
	var err error
	switch source {
	case sourceRate:
		rate, ok := raw["rate"].(map[string]any)
		if !ok {
			return costModel{}, costErr("a rate cost declares rate: {amount, currency}")
		}
		amount, err := costDecimal(rate["amount"], "rate.amount")
		if err != nil {
			return costModel{}, err
		}
		m.rate = &amount
		if m.currency, err = costCurrency(rate["currency"], "rate.currency"); err != nil {
			return costModel{}, err
		}
		m.qty, err = parseQuantity(rate["quantity"])
		return m, err
	case sourceReport:
		rep, ok := raw["reported"].(map[string]any)
		_, hasPath := rep["path"]
		meta, hasMeta := rep["meta"]
		if !ok || (!hasPath && !hasMeta) {
			return costModel{}, costErr("a reported cost declares reported: {path | meta [+ path], currency}")
		}
		if hasMeta {
			s, ok := meta.(string)
			if !ok || s == "" {
				return costModel{}, costErr("reported.meta must name a _meta key")
			}
			m.reportedMeta = s
		}
		if m.currency, err = costCurrency(rep["currency"], "reported.currency"); err != nil {
			return costModel{}, err
		}
		if hasPath {
			m.reportedPath, err = validPath(rep["path"], "reported.path")
		}
		return m, err
	case sourceSettled:
		return parseSettled(m, raw["settled"])
	}
	m.qty = quantity{constant: ptrDecimal(money.FromInt(1))}
	return m, nil
}

func ptrDecimal(d money.Decimal) *money.Decimal { return &d }

func parseSettled(m costModel, raw any) (costModel, error) {
	settled, _ := raw.(map[string]any)
	fetch, ok := settled["fetch"].(map[string]any)
	if !ok {
		return costModel{}, costErr("a settled cost declares settled: {fetch: {url, params, cost, currency}}")
	}
	url, ok := fetch["url"].(string)
	if !ok || !strings.HasPrefix(url, "https://") {
		return costModel{}, costErr("settled.fetch.url must be an https URL, got %s", pyRepr(fetch["url"]))
	}
	params, ok := fetch["params"].(map[string]any)
	if fetch["params"] != nil && !ok {
		return costModel{}, costErr("settled.fetch.params must map URL parameters to result paths")
	}
	var missing []string
	for _, n := range urlParamRe.FindAllStringSubmatch(url, -1) {
		if _, has := params[n[1]]; !has {
			missing = append(missing, "'"+n[1]+"'")
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return costModel{}, costErr("settled.fetch.url names [%s] that params do not read", strings.Join(missing, ", "))
	}
	sf := &settleFetch{url: url}
	if done, has := fetch["done"]; has && done != nil {
		d, _ := done.(map[string]any)
		values, ok := d["in"].([]any)
		if !ok || len(values) == 0 {
			return costModel{}, costErr("settled.fetch.done declares {path, in: [values]}")
		}
		for _, v := range values {
			if _, isStr := v.(string); !isStr {
				return costModel{}, costErr("settled.fetch.done declares {path, in: [values]}")
			}
			sf.doneIn = append(sf.doneIn, v.(string))
		}
		donePath, err := validPath(d["path"], "settled.fetch.done.path")
		if err != nil {
			return costModel{}, err
		}
		sf.donePath = donePath
	}
	names := make([]string, 0, len(params))
	for n := range params {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		ref := params[n]
		if r, isMap := ref.(map[string]any); isMap && len(r) == 1 && r["meta"] != nil {
			s, ok := r["meta"].(string)
			if !ok || s == "" {
				return costModel{}, costErr("settled.fetch.params.%s.meta must name a _meta key", n)
			}
			m.settleParams = append(m.settleParams, settleParam{n, valueRef{meta: s}})
			continue
		}
		p, err := validPath(ref, "settled.fetch.params."+n)
		if err != nil {
			return costModel{}, err
		}
		m.settleParams = append(m.settleParams, settleParam{n, valueRef{path: p}})
	}
	costPath, err := validPath(fetch["cost"], "settled.fetch.cost")
	if err != nil {
		return costModel{}, err
	}
	sf.costPath = costPath
	currency, err := costCurrency(fetch["currency"], "settled.fetch.currency")
	if err != nil {
		return costModel{}, err
	}
	if m.estimateCurrency != "" && m.estimateCurrency != currency {
		return costModel{}, costErr("estimate is in %s but the settled cost in %s", m.estimateCurrency, currency)
	}
	m.currency, m.settle = currency, sf
	return m, nil
}

// preCallCost is what a call will cost before it runs, or nil when nothing says.
func preCallCost(m costModel, args map[string]any) (*meteredCost, error) {
	if m.source == sourceRate && (m.qty.constant != nil || m.qty.arg != "") {
		return meterCost(m, args, nil, nil)
	}
	if m.source == sourceFree || m.source == sourceUnknown || m.estimate == nil {
		return nil, nil
	}
	return &meteredCost{quantity: money.FromInt(1), unit: m.unit, vendorCost: *m.estimate, currency: m.estimateCurrency, source: m.source}, nil
}

// meterCost is what one call cost from its arguments and result, or nil when nothing is known yet.
func meterCost(m costModel, args map[string]any, body any, meta map[string]any) (*meteredCost, error) {
	switch m.source {
	case sourceRate:
		if m.rate == nil {
			return nil, costErr("rate.amount is not declared")
		}
		q, err := m.qty.evaluate(args, body)
		if err != nil {
			return nil, err
		}
		return &meteredCost{quantity: q, unit: m.unit, vendorCost: m.rate.Mul(q), currency: m.currency, source: m.source, exact: m.exact}, nil
	case sourceReport:
		var value any
		var where string
		if m.reportedMeta != "" {
			v, ok := meta[m.reportedMeta]
			if !ok {
				return nil, costErr("the result's _meta carries no %s", m.reportedMeta)
			}
			value, where = v, m.reportedMeta
			if m.reportedPath != "" {
				var err error
				if value, err = readPath(value, m.reportedPath); err != nil {
					return nil, err
				}
				where = m.reportedMeta + m.reportedPath[1:]
			}
		} else {
			var err error
			where = m.reportedPath
			if value, err = readPath(body, where); err != nil {
				return nil, err
			}
		}
		cost, err := costDecimal(value, where)
		if err != nil {
			return nil, err
		}
		return &meteredCost{quantity: money.FromInt(1), unit: m.unit, vendorCost: cost, currency: m.currency, source: m.source, exact: m.exact}, nil
	case sourceSettled:
		params := map[string]string{}
		for _, p := range m.settleParams {
			var value any
			if p.ref.meta != "" {
				v, ok := meta[p.ref.meta]
				if !ok {
					return nil, costErr("the result's _meta carries no %s", p.ref.meta)
				}
				value = v
			} else {
				var err error
				if value, err = readPath(body, p.ref.path); err != nil {
					return nil, err
				}
			}
			s, ok := settleID(value)
			if !ok {
				return nil, costErr("settled.fetch.params.%s read %s, not an id", p.name, pyRepr(value))
			}
			params[p.name] = s
		}
		cost := money.Decimal{}
		if m.estimate != nil {
			cost = *m.estimate
		}
		return &meteredCost{quantity: money.FromInt(1), unit: m.unit, vendorCost: cost, currency: m.currency, source: m.source, settleParams: params}, nil
	}
	return nil, nil
}

func settleID(v any) (string, bool) {
	switch x := v.(type) {
	case string:
		return x, x != ""
	case float64:
		if x == float64(int64(x)) {
			return strconv.FormatInt(int64(x), 10), true
		}
	case int:
		return strconv.Itoa(x), true
	case int64:
		return strconv.FormatInt(x, 10), true
	}
	return "", false
}

// DeclaredRate is parse_cost_model over one cost declaration: the rate's
// amount, currency and unit when its source is a rate, nil otherwise.
func DeclaredRate(raw any) (rate *money.Decimal, currency, unit string, err error) {
	m, ok := raw.(map[string]any)
	if !ok {
		return nil, "", "", costErr("a cost declaration is an object")
	}
	cm, err := parseCostModel(m)
	if err != nil || cm.source != sourceRate {
		return nil, "", "", err
	}
	return cm.rate, cm.currency, cm.unit, nil
}
