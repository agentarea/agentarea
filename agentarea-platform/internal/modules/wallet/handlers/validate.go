package handlers

import (
	"context"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/service"
)

// Payment page bounds (get_payment_history Query).
const (
	defaultPageSize = 50
	maxPageSize     = 200
)

// input is what a route's parameters and body validated to. Its errors are
// kept, not raised: FastAPI solves the agent dependency (404) and the admin
// check ahead of reporting a bad body or query.
type input struct {
	errs   []httpx.FieldError
	create service.Create
	update service.Update
	fund   money.Decimal
	filter domain.PaymentFilter
	page   int
	size   int
}

type inputKey struct{}

func inputFrom(ctx context.Context) input {
	in, _ := ctx.Value(inputKey{}).(input)
	return in
}

// request is one route's parameters: the workspace path, then the query or
// body. The body is replaced by an empty object and the query by an empty
// one after reading, so the generated binder sees a well-formed request
// whatever was sent.
type request struct {
	query func(q url.Values, in *input)
	body  func(v any, in *input)
}

func (rq request) middleware(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var in input
			if fe := httpx.ValidateWorkspacePath(chi.URLParam(r, httpx.WorkspaceParam)); fe != nil {
				in.errs = append(in.errs, *fe)
			}
			if rq.query != nil {
				rq.query(r.URL.Query(), &in)
				r.URL.RawQuery = ""
			}
			if rq.body != nil {
				v, err := readBody(r)
				if err != nil {
					errs.Write(w, r, err)
					return
				}
				rq.body(v, &in)
				r.Body = io.NopCloser(strings.NewReader("{}"))
				r.ContentLength = 2
				r.Header.Set("Content-Type", "application/json")
			}
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), inputKey{}, in)))
		})
	}
}

func strictString(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) (string, bool, bool) {
	v, ok := o.Get(key)
	if !ok {
		return "", false, true
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType(at(loc, key)...))
		return "", true, false
	}
	return s, true, true
}

func optString(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) any {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType(at(loc, key)...))
		return nil
	}
	return s
}

func optInt(o wirejson.Object, key string, loc []any, errs *[]httpx.FieldError) any {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return nil
	}
	return intOf(v, at(loc, key), errs)
}

func intOf(v any, loc []any, errs *[]httpx.FieldError) any {
	switch x := v.(type) {
	case interface{ Int64() (int64, error) }:
		n, err := x.Int64()
		if err != nil {
			*errs = append(*errs, httpx.IntParsing(loc...))
			return nil
		}
		return n
	case wirejson.Float:
		f := float64(x)
		if f != float64(int64(f)) {
			*errs = append(*errs, httpx.IntFromFloat(loc...))
			return nil
		}
		return int64(f)
	case string:
		n, ok := httpx.ParseInt(x)
		if !ok || n.Overflow {
			*errs = append(*errs, httpx.IntParsing(loc...))
			return nil
		}
		return n.Value
	}
	*errs = append(*errs, httpx.IntType(loc...))
	return nil
}

// enum reads a StrEnum field; nullable admits null as unset.
func enum(o wirejson.Object, key string, choices []string, loc []any, nullable bool, errs *[]httpx.FieldError) (string, bool) {
	v, ok := o.Get(key)
	if !ok || (v == nil && nullable) {
		return "", false
	}
	s, isStr := v.(string)
	if !isStr || !domain.Valid(choices, s) {
		*errs = append(*errs, httpx.EnumError(choices, at(loc, key)...))
		return "", false
	}
	return s, true
}

func jsonBytes(o wirejson.Object) []byte {
	raw, err := wirejson.Marshal(o, wirejson.Dumps)
	if err != nil {
		return nil
	}
	return raw
}

// x402Config is X402ConfigSchema.model_dump(): every field, defaults filled.
func x402Config(v any, loc []any, errs *[]httpx.FieldError) []byte {
	if v == nil {
		return nil
	}
	o, ok := model(v, loc, errs)
	if !ok {
		return nil
	}
	out := wirejson.Object{}
	failed := false
	for _, f := range []struct{ key, def string }{
		{"network", "eip155:8453"}, {"facilitator_url", "https://x402.org/facilitator"},
		{"scheme", "exact"}, {"signer_type", "evm"},
	} {
		s, set, good := strictString(o, f.key, loc, errs)
		switch {
		case !good:
			failed = true
		case set:
			out = append(out, wirejson.Member{Key: f.key, Value: s})
		default:
			out = append(out, wirejson.Member{Key: f.key, Value: f.def})
		}
	}
	if failed {
		return nil
	}
	return jsonBytes(out)
}

// mppConfig is MPPConfigSchema.model_dump(mode="json").
func mppConfig(v any, loc []any, errs *[]httpx.FieldError) []byte {
	if v == nil {
		return nil
	}
	o, ok := model(v, loc, errs)
	if !ok {
		return nil
	}
	before := len(*errs)
	methods := []any{"charge"}
	if raw, set := o.Get("payment_method_types"); set {
		list, isList := raw.([]any)
		if !isList {
			*errs = append(*errs, httpx.ListType(at(loc, "payment_method_types")...))
		} else {
			methods = make([]any, len(list))
			for i, item := range list {
				s, isStr := item.(string)
				if !isStr {
					*errs = append(*errs, httpx.StringType(at(loc, "payment_method_types", i)...))
					continue
				}
				methods[i] = s
			}
		}
	}
	var session any
	if raw, set := o.Get("session_budget_usd"); !set {
		*errs = append(*errs, httpx.Missing(at(loc, "session_budget_usd")...))
	} else if d, good := nonNegative(raw, at(loc, "session_budget_usd"), errs); good {
		session = d.String()
	}
	stripe := optString(o, "stripe_profile_id", loc, errs)
	chain := optInt(o, "chain_id", loc, errs)
	rpc := optString(o, "rpc_url", loc, errs)
	currency := optString(o, "currency", loc, errs)
	recipient := optString(o, "recipient", loc, errs)
	var decimals any = int64(6)
	if raw, set := o.Get("decimals"); set {
		decimals = intOf(raw, at(loc, "decimals"), errs)
	}
	if len(*errs) > before {
		return nil
	}
	return jsonBytes(wirejson.Object{
		{Key: "payment_method_types", Value: methods}, {Key: "session_budget_usd", Value: session},
		{Key: "stripe_profile_id", Value: stripe}, {Key: "chain_id", Value: chain}, {Key: "rpc_url", Value: rpc},
		{Key: "currency", Value: currency}, {Key: "recipient", Value: recipient}, {Key: "decimals", Value: decimals},
	})
}

func credentials(v any, loc []any, errs *[]httpx.FieldError) *service.Credentials {
	if v == nil {
		return nil
	}
	o, ok := model(v, loc, errs)
	if !ok {
		return nil
	}
	c := &service.Credentials{}
	for _, f := range []struct {
		key string
		dst **string
	}{{"x402_private_key", &c.X402PrivateKey}, {"mpp_tempo_key", &c.MPPTempoKey}} {
		if s := optString(o, f.key, loc, errs); s != nil {
			str := s.(string)
			*f.dst = &str
		}
	}
	return c
}

// createBody is CreateWalletRequest.
func createBody(v any, in *input) {
	loc := []any{"body"}
	o, ok := model(v, loc, &in.errs)
	if !ok {
		return
	}
	if t, set := enum(o, "wallet_type", domain.WalletTypes(), loc, false, &in.errs); set {
		in.create.Type = t
	} else if _, present := o.Get("wallet_type"); !present {
		in.errs = append(in.errs, httpx.Missing("body", "wallet_type"))
	}
	if x, set := o.Get("x402_config"); set {
		in.create.X402Config = x402Config(x, at(loc, "x402_config"), &in.errs)
	}
	if x, set := o.Get("mpp_config"); set {
		in.create.MPPConfig = mppConfig(x, at(loc, "mpp_config"), &in.errs)
	}
	if x, set := o.Get("credentials"); set {
		in.create.Credentials = credentials(x, at(loc, "credentials"), &in.errs)
	}
	in.create.Budget = money.Zero()
	if x, set := o.Get("service_budget_usd"); set {
		if d, good := budget(x, at(loc, "service_budget_usd"), &in.errs); good {
			in.create.Budget = d
		}
	}
	in.create.Period = domain.BudgetPeriods()[0]
	if p, set := enum(o, "service_budget_period", domain.BudgetPeriods(), loc, false, &in.errs); set {
		in.create.Period = p
	}
}

// updateBody is UpdateWalletRequest: a null field is left unchanged.
func updateBody(v any, in *input) {
	loc := []any{"body"}
	o, ok := model(v, loc, &in.errs)
	if !ok {
		return
	}
	if t, set := enum(o, "wallet_type", domain.WalletTypes(), loc, true, &in.errs); set {
		in.update.Type = &t
	}
	if x, set := o.Get("x402_config"); set {
		in.update.X402Config = x402Config(x, at(loc, "x402_config"), &in.errs)
	}
	if x, set := o.Get("mpp_config"); set {
		in.update.MPPConfig = mppConfig(x, at(loc, "mpp_config"), &in.errs)
	}
	if x, set := o.Get("credentials"); set {
		in.update.Credentials = credentials(x, at(loc, "credentials"), &in.errs)
	}
	if x, set := o.Get("service_budget_usd"); set && x != nil {
		if d, good := budget(x, at(loc, "service_budget_usd"), &in.errs); good {
			in.update.Budget = &d
		}
	}
	if p, set := enum(o, "service_budget_period", domain.BudgetPeriods(), loc, true, &in.errs); set {
		in.update.Period = &p
	}
	if s, set := enum(o, "status", domain.Statuses(), loc, true, &in.errs); set {
		in.update.Status = &s
	}
}

// fundBody is FundWalletRequest.
func fundBody(v any, in *input) {
	loc := []any{"body"}
	o, ok := model(v, loc, &in.errs)
	if !ok {
		return
	}
	x, set := o.Get("service_budget_usd")
	if !set {
		in.errs = append(in.errs, httpx.Missing("body", "service_budget_usd"))
		return
	}
	if d, good := budget(x, at(loc, "service_budget_usd"), &in.errs); good {
		in.fund = d
	}
}

var isoDatetime = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})(?:[T t_](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,6})\d*)?)?(Z|z|[+-]\d{2}(?::?\d{2})?)?)?$`)

// parseDatetime is pydantic's datetime from a query string, made naive UTC
// (NaiveUtcDatetime): an ISO 8601 date or datetime, or Unix seconds
// (milliseconds above 2e10).
func parseDatetime(s string) (time.Time, bool) {
	if f, err := strconv.ParseFloat(s, 64); err == nil && !strings.ContainsAny(s, "eEnNiI") {
		if f > 2e10 || f < -2e10 {
			f /= 1000
		}
		sec := int64(f)
		return time.Unix(sec, int64((f-float64(sec))*1e9)).UTC().Round(time.Microsecond), true
	}
	m := isoDatetime.FindStringSubmatch(s)
	if m == nil {
		return time.Time{}, false
	}
	n := func(i int) int { v, _ := strconv.Atoi(m[i]); return v }
	year, month, day := n(1), n(2), n(3)
	var hour, minute, sec, micro int
	if m[4] != "" {
		hour, minute = n(4), n(5)
		if m[6] != "" {
			sec = n(6)
		}
		if m[7] != "" {
			micro, _ = strconv.Atoi((m[7] + "000000")[:6])
		}
	}
	if month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || sec > 59 {
		return time.Time{}, false
	}
	t := time.Date(year, time.Month(month), day, hour, minute, sec, micro*1000, time.UTC)
	if t.Day() != day {
		return time.Time{}, false
	}
	if tz := m[8]; tz != "" && tz != "Z" && tz != "z" {
		sign := 1
		if tz[0] == '-' {
			sign = -1
		}
		digits := strings.ReplaceAll(tz[1:], ":", "")
		h, _ := strconv.Atoi(digits[:2])
		mm := 0
		if len(digits) == 4 {
			mm, _ = strconv.Atoi(digits[2:])
		}
		t = t.Add(-time.Duration(sign) * (time.Duration(h)*time.Hour + time.Duration(mm)*time.Minute))
	}
	return t, true
}

func datetimeError(key string) httpx.FieldError {
	return httpx.FieldError{
		Type: "datetime_from_date_parsing", Loc: []any{"query", key},
		Msg: "Input should be a valid datetime or date, invalid character in year",
		Ctx: wirejson.Object{{Key: "error", Value: "invalid character in year"}},
	}
}

func lastValue(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

// paymentsQuery is get_payment_history's Query parameters, in signature order.
func paymentsQuery(q url.Values, in *input) {
	f := &in.filter
	if v, ok := lastValue(q, "protocol"); ok {
		f.Protocol = &v
	}
	if v, ok := lastValue(q, "status"); ok {
		f.Status = &v
	}
	for _, k := range []struct {
		key string
		dst **time.Time
	}{{"from_date", &f.From}, {"to_date", &f.To}} {
		if v, ok := lastValue(q, k.key); ok {
			t, good := parseDatetime(v)
			if !good {
				in.errs = append(in.errs, datetimeError(k.key))
				continue
			}
			*k.dst = &t
		}
	}
	in.page, in.size = 1, defaultPageSize
	if v, ok := lastValue(q, "page"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: httpx.MaxPage, HasLe: true}, "query", "page")
		if fe != nil {
			in.errs = append(in.errs, *fe)
		} else {
			in.page = int(n)
		}
	}
	if v, ok := lastValue(q, "page_size"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: maxPageSize, HasLe: true}, "query", "page_size")
		if fe != nil {
			in.errs = append(in.errs, *fe)
		} else {
			in.size = int(n)
		}
	}
}
