package domain

import (
	"testing"
	"time"
)

func runs(t *testing.T, expr, tz string, start, end time.Time, limit int) []time.Time {
	t.Helper()
	c, err := ParseCron(expr)
	if err != nil {
		t.Fatal(err)
	}
	loc, err := Zone(tz)
	if err != nil {
		t.Fatal(err)
	}
	return c.Runs(loc, start, end, limit)
}

func TestCronFiresAfterStartUpToEnd(t *testing.T) {
	start := time.Date(2026, 11, 15, 9, 0, 0, 0, time.UTC)
	got := runs(t, "0 9,18 * * *", "", start, start.Add(48*time.Hour), 10)
	want := []string{"2026-11-15T18:00:00Z", "2026-11-16T09:00:00Z", "2026-11-16T18:00:00Z", "2026-11-17T09:00:00Z"}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for i, w := range want {
		if got[i].Format(time.RFC3339) != w {
			t.Fatalf("run %d = %s, want %s", i, got[i].Format(time.RFC3339), w)
		}
	}
}

func TestCronDayOfMonthAndDayOfWeekBothMatch(t *testing.T) {
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	got := runs(t, "0 12 13 * fri", "", start, start.AddDate(1, 0, 0), 10)
	if len(got) == 0 {
		t.Fatal("no Friday the 13th in 2026")
	}
	for _, at := range got {
		if at.Day() != 13 || at.Weekday() != time.Friday {
			t.Fatalf("%v is not a Friday the 13th", at)
		}
	}
}

func TestCronYearFieldAndNames(t *testing.T) {
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	got := runs(t, "30 6 1 jan,jul * 2027", "", start, start.AddDate(3, 0, 0), 10)
	if len(got) != 2 || got[0] != time.Date(2027, 1, 1, 6, 30, 0, 0, time.UTC) || got[1] != time.Date(2027, 7, 1, 6, 30, 0, 0, time.UTC) {
		t.Fatalf("got %v", got)
	}
}

func TestCronSundayIsSevenToo(t *testing.T) {
	start := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	a, b := runs(t, "0 0 * * 7", "", start, start.AddDate(0, 0, 14), 5), runs(t, "0 0 * * 0", "", start, start.AddDate(0, 0, 14), 5)
	if len(a) != 2 || len(a) != len(b) || a[0] != b[0] {
		t.Fatalf("7 = %v, 0 = %v", a, b)
	}
}

func TestCronLastDayOfMonth(t *testing.T) {
	start := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	got := runs(t, "0 0 L * *", "", start, start.AddDate(0, 2, 0), 5)
	if len(got) != 2 || got[0].Day() != 28 || got[1].Day() != 31 {
		t.Fatalf("got %v", got)
	}
}

func TestCronSkipsWallTimeDSTRemoves(t *testing.T) {
	start := time.Date(2026, 3, 7, 0, 0, 0, 0, time.UTC)
	got := runs(t, "30 2 * * *", "America/New_York", start, start.AddDate(0, 0, 3), 10)
	for _, at := range got {
		if l := at.In(mustZone(t, "America/New_York")); l.Day() == 8 {
			t.Fatalf("fired at %v on the spring-forward day", l)
		}
	}
	if len(got) != 2 {
		t.Fatalf("got %v, want the 7th and 9th", got)
	}
}

func mustZone(t *testing.T, name string) *time.Location {
	t.Helper()
	loc, err := Zone(name)
	if err != nil {
		t.Fatal(err)
	}
	return loc
}

func TestCronLimitAndRunsPerDay(t *testing.T) {
	c, err := ParseCron("*/15 9-10 * * mon-fri")
	if err != nil {
		t.Fatal(err)
	}
	if c.RunsPerDay() != 8 {
		t.Fatalf("runs per day %d", c.RunsPerDay())
	}
	start := time.Date(2026, 11, 16, 0, 0, 0, 0, time.UTC)
	if got := c.Runs(time.UTC, start, start.AddDate(0, 0, 7), 3); len(got) != 3 {
		t.Fatalf("limit ignored: %v", got)
	}
}

func TestCronRefusesBadExpressionsAndZones(t *testing.T) {
	for _, e := range []string{"", "* * * *", "61 * * * *", "* * * * * * *", "0 0 * * mon-xyz", "0 0 * * * 1969"} {
		if _, err := ParseCron(e); err == nil {
			t.Fatalf("%q parsed", e)
		}
	}
	for _, z := range []string{"Local", "Mars/Olympus"} {
		if _, err := Zone(z); err == nil {
			t.Fatalf("zone %q accepted", z)
		}
	}
}
