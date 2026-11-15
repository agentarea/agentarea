package domain

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Cron is a parsed cron expression read as Temporal reads it
// (_schedule_preview.py): five fields, or six with the year last; a
// restricted day of month and day of week must both match.
type Cron struct {
	minutes, hours, doms, months, dows []int
	years                              map[int]bool
	lastDOM                            bool
}

func monthNames() map[string]int {
	return map[string]int{"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
}

func dayNames() map[string]int {
	return map[string]int{"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
}

// ParseCron reads expr; an error is a schedule the preview cannot expand.
func ParseCron(expr string) (Cron, error) {
	fields := strings.Fields(expr)
	if len(fields) != 5 && len(fields) != 6 {
		return Cron{}, fmt.Errorf("cron expression %q must have 5 or 6 fields", expr)
	}
	var c Cron
	var err error
	if c.minutes, err = field(fields[0], 0, 59, nil); err != nil {
		return Cron{}, err
	}
	if c.hours, err = field(fields[1], 0, 23, nil); err != nil {
		return Cron{}, err
	}
	if strings.EqualFold(fields[2], "L") {
		c.lastDOM = true
	} else if c.doms, err = field(fields[2], 1, 31, nil); err != nil {
		return Cron{}, err
	}
	if c.months, err = field(fields[3], 1, 12, monthNames()); err != nil {
		return Cron{}, err
	}
	dows, err := field(fields[4], 0, 7, dayNames())
	if err != nil {
		return Cron{}, err
	}
	seen := map[int]bool{}
	for _, d := range dows {
		if d == 7 {
			d = 0
		}
		if !seen[d] {
			seen[d] = true
			c.dows = append(c.dows, d)
		}
	}
	if len(fields) == 6 {
		years, err := field(fields[5], 1970, 2099, nil)
		if err != nil {
			return Cron{}, err
		}
		c.years = map[int]bool{}
		for _, y := range years {
			c.years[y] = true
		}
	}
	return c, nil
}

func value(s string, names map[string]int) (int, error) {
	if n, ok := names[strings.ToLower(s)]; ok {
		return n, nil
	}
	return strconv.Atoi(s)
}

// field expands one comma list of *, ?, n, a-b and a step on any of them.
func field(spec string, lo, hi int, names map[string]int) ([]int, error) {
	in := map[int]bool{}
	for part := range strings.SplitSeq(spec, ",") {
		base, stepText, hasStep := strings.Cut(part, "/")
		step := 1
		if hasStep {
			n, err := strconv.Atoi(stepText)
			if err != nil || n <= 0 {
				return nil, fmt.Errorf("cron field %q has a bad step", spec)
			}
			step = n
		}
		from, to := lo, hi
		switch {
		case base == "*" || base == "?":
		case strings.Contains(base, "-"):
			a, b, _ := strings.Cut(base, "-")
			x, err1 := value(a, names)
			y, err2 := value(b, names)
			if err1 != nil || err2 != nil {
				return nil, fmt.Errorf("cron field %q has a bad range", spec)
			}
			from, to = x, y
		default:
			x, err := value(base, names)
			if err != nil {
				return nil, fmt.Errorf("cron field %q has a bad value", spec)
			}
			from = x
			if !hasStep {
				to = x
			}
		}
		if from < lo || to > hi || from > to {
			return nil, fmt.Errorf("cron field %q is out of range", spec)
		}
		for v := from; v <= to; v += step {
			in[v] = true
		}
	}
	out := make([]int, 0, len(in))
	for v := lo; v <= hi; v++ {
		if in[v] {
			out = append(out, v)
		}
	}
	return out, nil
}

// RunsPerDay is how many times the schedule fires on a day it runs.
func (c Cron) RunsPerDay() int { return len(c.minutes) * len(c.hours) }

func has(set []int, v int) bool {
	for _, x := range set {
		if x == v {
			return true
		}
	}
	return false
}

func (c Cron) runsOn(day time.Time) bool {
	if c.years != nil && !c.years[day.Year()] {
		return false
	}
	if !has(c.months, int(day.Month())) || !has(c.dows, int(day.Weekday())) {
		return false
	}
	if c.lastDOM {
		return day.AddDate(0, 0, 1).Day() == 1
	}
	return has(c.doms, day.Day())
}

// Zone is the location a schedule runs in; "" is UTC.
func Zone(name string) (*time.Location, error) {
	if name == "" {
		name = "UTC"
	}
	if name == "Local" {
		return nil, fmt.Errorf("unknown timezone %q", name)
	}
	loc, err := time.LoadLocation(name)
	if err != nil {
		return nil, fmt.Errorf("unknown timezone %q", name)
	}
	return loc, nil
}

// Runs is the firings after start and up to end, at most limit, in UTC. A
// wall time a DST change removes does not fire; a repeated one fires once.
func (c Cron) Runs(loc *time.Location, start, end time.Time, limit int) []time.Time {
	var out []time.Time
	from := start.In(loc)
	day := time.Date(from.Year(), from.Month(), from.Day(), 0, 0, 0, 0, time.UTC)
	last := end.In(loc)
	lastDay := time.Date(last.Year(), last.Month(), last.Day(), 0, 0, 0, 0, time.UTC)
	for ; !day.After(lastDay) && len(out) < limit; day = day.AddDate(0, 0, 1) {
		if !c.runsOn(day) {
			continue
		}
		for _, h := range c.hours {
			for _, m := range c.minutes {
				at := time.Date(day.Year(), day.Month(), day.Day(), h, m, 0, 0, loc)
				if at.Hour() != h || at.Minute() != m || at.Day() != day.Day() {
					continue
				}
				if !at.After(start) {
					continue
				}
				if at.After(end) || len(out) >= limit {
					return out
				}
				out = append(out, at.UTC())
			}
		}
	}
	return out
}
