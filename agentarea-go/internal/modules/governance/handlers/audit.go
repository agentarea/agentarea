package handlers

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/service"
)

type auditList struct {
	query  domain.AuditQuery
	cursor string
}

// Audit page bounds (list_audit_logs Query).
const (
	DefaultAuditLimit = 50
	MaxAuditLimit     = 100
)

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

func auditQuery(q url.Values, in *input, errs *[]httpx.FieldError) {
	f := &in.query
	for _, k := range []struct {
		key string
		dst **string
	}{{"action", &f.Action}, {"actor_id", &f.ActorID}, {"resource_type", &f.ResourceType}, {"resource_id", &f.ResourceID}} {
		if v, ok := last(q, k.key); ok && v != "" {
			*k.dst = &v
		}
	}
	for _, k := range []struct {
		key string
		dst **time.Time
	}{{"since", &f.Since}, {"until", &f.Until}} {
		if v, ok := last(q, k.key); ok {
			t, good := parseDatetime(v)
			if !good {
				*errs = append(*errs, datetimeError(k.key))
				continue
			}
			*k.dst = &t
		}
	}
	if v, ok := last(q, "cursor"); ok {
		id, fe := httpx.ValidateUUID(v, "query", "cursor")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			u := uuid.MustParse(id)
			b := [16]byte(u)
			f.Cursor, in.cursor = &b, id
		}
	}
	f.Limit = DefaultAuditLimit
	if v, ok := last(q, "limit"); ok {
		n, fe := httpx.ValidateInt(v, httpx.IntBounds{Ge: 1, HasGe: true, Le: MaxAuditLimit, HasLe: true}, "query", "limit")
		if fe != nil {
			*errs = append(*errs, *fe)
		} else {
			f.Limit = int(n)
		}
	}
}

func rawJSON(raw []byte) (any, error) {
	if raw == nil {
		return nil, nil
	}
	return wirejson.Unmarshal(raw)
}

// auditJSON is AuditEventResponse; changes that are not a list read as null.
func auditJSON(e domain.AuditEvent) (wirejson.Object, error) {
	changes, err := rawJSON(e.RawChanges)
	if err != nil {
		return nil, err
	}
	if _, isList := changes.([]any); !isList {
		changes = nil
	}
	meta, err := rawJSON(e.RawMetadata)
	if err != nil {
		return nil, err
	}
	return wirejson.Object{
		{Key: "id", Value: e.ID},
		{Key: "created_at", Value: utcISO(e.CreatedAt)},
		{Key: "actor_id", Value: e.ActorID},
		{Key: "actor_type", Value: e.ActorType},
		{Key: "workspace_id", Value: e.WorkspaceID},
		{Key: "source_ip", Value: e.SourceIP},
		{Key: "user_agent", Value: e.UserAgent},
		{Key: "request_id", Value: e.RequestID},
		{Key: "action", Value: e.Action},
		{Key: "resource_type", Value: e.ResourceType},
		{Key: "resource_id", Value: e.ResourceID},
		{Key: "changes", Value: changes},
		{Key: "event_metadata", Value: meta},
	}, nil
}

func (s *Server) ListAuditLogsV1AuditLogsGet(ctx context.Context, _ gen.ListAuditLogsV1AuditLogsGetRequestObject) (gen.ListAuditLogsV1AuditLogsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	in := inputFrom(ctx)
	events, err := s.svc.AuditLogs(ctx, c, in.query)
	if errors.Is(err, service.ErrUnknownCursor) {
		return nil, httpx.HTTPError(http.StatusBadRequest, "Unknown audit cursor "+in.cursor)
	}
	if err != nil {
		return nil, err
	}
	out := make([]any, len(events))
	for i, e := range events {
		if out[i], err = auditJSON(e); err != nil {
			return nil, err
		}
	}
	var next any
	if len(events) == in.query.Limit {
		next = events[len(events)-1].ID
	}
	return ok(wirejson.Object{{Key: "events", Value: out}, {Key: "next_cursor", Value: next}}), nil
}
