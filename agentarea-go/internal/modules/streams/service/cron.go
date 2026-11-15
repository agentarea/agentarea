package service

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// The grammar Temporal's cron strings share with classic cron (domain/cron.py): five
// fields, or six with a trailing year; each a comma list of *, ?, a value or a
// low-high range, each optionally followed by /step. Temporal evaluates the
// schedule (day of month AND day of week); this only refuses what it cannot run.
type cronField struct {
	name            string
	lowest, highest int
	names           []string
}

func cronFields() []cronField {
	return []cronField{
		{"minute", 0, 59, nil},
		{"hour", 0, 23, nil},
		{"day of month", 1, 31, nil},
		{"month", 1, 12, []string{"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}},
		{"day of week", 0, 7, []string{"sun", "mon", "tue", "wed", "thu", "fri", "sat"}},
		{"year", 1970, 2199, nil},
	}
}

var cronItem = regexp.MustCompile(`^(\*|\?|[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)(?:/([0-9]+))?$`)

func (f cronField) value(token string) (int, bool) {
	n, err := strconv.Atoi(token)
	if err != nil {
		found := false
		for i, name := range f.names {
			if strings.ToLower(token) == name {
				n, found = i+f.lowest, true
				break
			}
		}
		if !found {
			return 0, false
		}
	}
	return n, f.lowest <= n && n <= f.highest
}

func (f cronField) check(field string) string {
	for _, item := range strings.Split(field, ",") {
		m := cronItem.FindStringSubmatch(item)
		if m == nil {
			return fmt.Sprintf("invalid %s field %s", f.name, domain.PyRepr(field))
		}
		if m[2] != "" && strings.Trim(m[2], "0") == "" {
			return f.name + " step cannot be 0"
		}
		base := m[1]
		if base == "*" || base == "?" {
			continue
		}
		var values []int
		for _, token := range strings.Split(base, "-") {
			v, ok := f.value(token)
			if !ok {
				return fmt.Sprintf("%s must be between %d and %d, got %s", f.name, f.lowest, f.highest, domain.PyRepr(base))
			}
			values = append(values, v)
		}
		if len(values) == 2 && values[0] > values[1] {
			return fmt.Sprintf("%s range %s runs backwards", f.name, domain.PyRepr(base))
		}
	}
	return ""
}

// CronError is cron_expression_error: why expr is not a schedule Temporal can run, "" when it is.
func CronError(expr string) string {
	fields := strings.Fields(expr)
	if len(fields) != 5 && len(fields) != 6 {
		return "Cron expression must have 5 or 6 parts"
	}
	spec := cronFields()
	for i, field := range fields {
		if e := spec[i].check(field); e != "" {
			return "Invalid cron expression: " + e
		}
	}
	return ""
}

// CheckCron refuses what CronError refuses.
func CheckCron(expr string) error {
	if e := CronError(expr); e != "" {
		return domain.Invalid(e)
	}
	return nil
}

// CheckTimezone refuses a name that is not an IANA zone (timezone_error).
func CheckTimezone(name string) error {
	if name == "" || name == "Local" {
		return domain.Invalid(fmt.Sprintf("Unknown time zone %s; use an IANA name such as 'Europe/Berlin'", domain.PyRepr(name)))
	}
	if _, err := time.LoadLocation(name); err != nil {
		return domain.Invalid(fmt.Sprintf("Unknown time zone %s; use an IANA name such as 'Europe/Berlin'", domain.PyRepr(name)))
	}
	return nil
}
