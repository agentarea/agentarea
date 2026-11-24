package openapispec

import (
	"encoding/json"
	"math/big"
	"regexp"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// The checks of tool_cost.parse_cost_model: a malformed declaration is the
// document's fault (ToolCostError, a ValueError). Metering reads the
// declaration on the runs side; here it is only refused or accepted.

var (
	costCurrency = regexp.MustCompile(`^[A-Z]{3}$`)
	costPath     = regexp.MustCompile(`^\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])*$`)
	costURLParam = regexp.MustCompile(`\{([A-Za-z_][A-Za-z0-9_]*)\}`)
)

func costSources() map[string]bool {
	return map[string]bool{"free": true, "rate": true, "reported": true, "settled": true, "unknown": true}
}

func costValidPath(v any, where string) error {
	s, ok := v.(string)
	if !ok || !costPath.MatchString(s) {
		return errorf("%s must be a path like $.field, got %s", where, repr(v))
	}
	return nil
}

func costDecimal(v any, where string) error {
	var text string
	switch t := v.(type) {
	case bool:
		return errorf("%s must be a number", where)
	case json.Number:
		text = t.String()
	case wirejson.Float:
		text = wirejson.FormatFloat(float64(t))
	case float64:
		text = wirejson.FormatFloat(t)
	case string:
		text = strings.TrimSpace(t)
	case nil:
		text = "None"
	default:
		return errorf("%s must be a number, got %s", where, repr(v))
	}
	r, ok := new(big.Rat).SetString(text)
	if !ok {
		low := strings.ToLower(strings.TrimLeft(text, "+-"))
		if low == "inf" || low == "infinity" || low == "nan" || low == "snan" {
			return errorf("%s must be a non-negative number, got %s", where, repr(v))
		}
		return errorf("%s must be a number, got %s", where, repr(v))
	}
	if r.Sign() < 0 {
		return errorf("%s must be a non-negative number, got %s", where, repr(v))
	}
	return nil
}

func costCurrencyOf(v any, where string) (string, error) {
	s, ok := v.(string)
	if ok && s == "USDC" {
		s = "USD"
	}
	if !ok || !costCurrency.MatchString(s) {
		return "", errorf("%s must be an ISO 4217 code like RUB, got %s", where, repr(v))
	}
	return s, nil
}

func costQuantity(raw any) error {
	if raw == nil {
		return nil
	}
	o, ok := asObject(raw)
	if !ok {
		return costDecimal(raw, "rate.quantity")
	}
	allowed := map[string]bool{"arg": true, "default": true, "count": true, "path": true}
	nonDefault := 0
	for _, m := range o {
		if !allowed[m.Key] {
			return errorf("rate.quantity must be one of arg, count, path; got %s", repr(raw))
		}
		if m.Key != "default" {
			nonDefault++
		}
	}
	if nonDefault != 1 {
		return errorf("rate.quantity must be one of arg, count, path; got %s", repr(raw))
	}
	if arg, ok := o.Get("arg"); ok {
		if s, isStr := arg.(string); !isStr || s == "" {
			return errorf("rate.quantity.arg must name an argument")
		}
		if d := get(o, "default", nil); d != nil {
			return costDecimal(d, "rate.quantity.default")
		}
		return nil
	}
	if has(o, "default") {
		return errorf("rate.quantity.default applies only to arg")
	}
	if c, ok := o.Get("count"); ok {
		return costValidPath(c, "rate.quantity.count")
	}
	return costValidPath(get(o, "path", nil), "rate.quantity.path")
}

func costValueRef(raw any, where string) error {
	if o, ok := asObject(raw); ok && len(o) == 1 && o[0].Key == "meta" {
		if s, isStr := o[0].Value.(string); !isStr || s == "" {
			return errorf("%s.meta must name a _meta key", where)
		}
		return nil
	}
	return costValidPath(raw, where)
}

func costSettle(raw any) (string, error) {
	var fetch wirejson.Object
	if o, ok := asObject(raw); ok {
		fetch, _ = asObject(get(o, "fetch", nil))
	}
	if fetch == nil {
		return "", errorf("a settled cost declares settled: {fetch: {url, params, cost, currency}}")
	}
	u, ok := get(fetch, "url", nil).(string)
	if !ok || !strings.HasPrefix(u, "https://") {
		return "", errorf("settled.fetch.url must be an https URL, got %s", repr(get(fetch, "url", nil)))
	}
	params, ok := asObject(or(get(fetch, "params", nil), wirejson.Object{}))
	if !ok {
		return "", errorf("settled.fetch.params must map URL parameters to result paths")
	}
	var missing []string
	for _, m := range costURLParam.FindAllStringSubmatch(u, -1) {
		if !has(params, m[1]) && !contains(missing, m[1]) {
			missing = append(missing, m[1])
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		items := make([]any, len(missing))
		for i, s := range missing {
			items[i] = s
		}
		return "", errorf("settled.fetch.url names %s that params do not read", repr(items))
	}
	if done := get(fetch, "done", nil); done != nil {
		var values []any
		var doneObj wirejson.Object
		if o, ok := asObject(done); ok {
			doneObj = o
			values, _ = get(o, "in", nil).([]any)
		}
		valid := len(values) > 0
		for _, v := range values {
			if _, isStr := v.(string); !isStr {
				valid = false
			}
		}
		if !valid {
			return "", errorf("settled.fetch.done declares {path, in: [values]}")
		}
		if err := costValidPath(get(doneObj, "path", nil), "settled.fetch.done.path"); err != nil {
			return "", err
		}
	}
	for _, m := range params {
		if err := costValueRef(m.Value, "settled.fetch.params."+m.Key); err != nil {
			return "", err
		}
	}
	if err := costValidPath(get(fetch, "cost", nil), "settled.fetch.cost"); err != nil {
		return "", err
	}
	return costCurrencyOf(get(fetch, "currency", nil), "settled.fetch.currency")
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// CostSource is parse_cost_model's check of a declaration; it returns the
// declared source ("unknown" for nil).
func CostSource(raw any) (string, error) {
	if raw == nil {
		return "unknown", nil
	}
	o, ok := asObject(raw)
	if !ok {
		return "", errorf("a cost declaration must be an object, got %s", repr(raw))
	}
	src, _ := get(o, "source", nil).(string)
	if !costSources()[src] {
		return "", errorf("unknown cost source %s", repr(get(o, "source", nil)))
	}
	if u := get(o, "unit", nil); truthy(u) {
		if _, isStr := u.(string); !isStr {
			return "", errorf("unit must be a string")
		}
	}
	if ex, ok := o.Get("exact"); ok {
		if _, isBool := ex.(bool); !isBool {
			return "", errorf("exact must be true or false")
		}
	}
	var estimateCurrency string
	if est := get(o, "estimate", nil); est != nil {
		e, ok := asObject(est)
		if !ok {
			return "", errorf("estimate declares {amount, currency}")
		}
		if err := costDecimal(get(e, "amount", nil), "estimate.amount"); err != nil {
			return "", err
		}
		c, err := costCurrencyOf(get(e, "currency", nil), "estimate.currency")
		if err != nil {
			return "", err
		}
		estimateCurrency = c
	}
	switch src {
	case "rate":
		rate, ok := asObject(get(o, "rate", nil))
		if !ok {
			return "", errorf("a rate cost declares rate: {amount, currency}")
		}
		if err := costDecimal(get(rate, "amount", nil), "rate.amount"); err != nil {
			return "", err
		}
		if _, err := costCurrencyOf(get(rate, "currency", nil), "rate.currency"); err != nil {
			return "", err
		}
		return src, costQuantity(get(rate, "quantity", nil))
	case "reported":
		rep, ok := asObject(get(o, "reported", nil))
		if !ok || (!has(rep, "path") && !has(rep, "meta")) {
			return "", errorf("a reported cost declares reported: {path | meta [+ path], currency}")
		}
		if meta, ok := rep.Get("meta"); ok {
			if s, isStr := meta.(string); !isStr || s == "" {
				return "", errorf("reported.meta must name a _meta key")
			}
		}
		if _, err := costCurrencyOf(get(rep, "currency", nil), "reported.currency"); err != nil {
			return "", err
		}
		if p, ok := rep.Get("path"); ok {
			return src, costValidPath(p, "reported.path")
		}
		return src, nil
	case "settled":
		currency, err := costSettle(get(o, "settled", nil))
		if err != nil {
			return "", err
		}
		if estimateCurrency != "" && estimateCurrency != currency {
			return "", errorf("estimate is in %s but the settled cost in %s", estimateCurrency, currency)
		}
	}
	return src, nil
}

// CheckConnectionCost is parse_connection_cost: a member's own cost on a
// connection is a rate, a reported field or free.
func CheckConnectionCost(raw any) error {
	src, err := CostSource(raw)
	if err != nil {
		return err
	}
	if src != "rate" && src != "reported" && src != "free" {
		return errorf("a connection's own cost is a rate, a reported field or free, not %s", src)
	}
	return nil
}

// CheckPayers is connector_payers: nil is the workspace; otherwise a
// non-empty list of platform and workspace.
func CheckPayers(raw any) error {
	if raw == nil {
		return nil
	}
	list, ok := raw.([]any)
	if !ok || len(list) == 0 {
		return errorf("payers must be a non-empty list, got %s", repr(raw))
	}
	for _, v := range list {
		if s, _ := v.(string); s != "platform" && s != "workspace" {
			return errorf("unknown payer in %s", repr(raw))
		}
	}
	return nil
}
