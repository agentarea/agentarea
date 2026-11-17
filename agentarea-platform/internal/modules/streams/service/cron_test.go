package service_test

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

func TestCronError(t *testing.T) {
	cases := map[string]string{
		"0 9 * * *":                        "",
		"0 9 * * 1-5 2027":                 "",
		"0 9 ? * MON":                      "",
		"*/15 0-23/2 1,15 jan-mar sun-sat": "",
		"0 0 1 1 * 2199":                   "",
		"0 9 13 * 5":                       "",
		"0 9 * *":                          "Cron expression must have 5 or 6 parts",
		"0 9 * * * * *":                    "Cron expression must have 5 or 6 parts",
		"60 9 * * *":                       "Invalid cron expression: minute must be between 0 and 59, got '60'",
		"0 9 * * * 1969":                   "Invalid cron expression: year must be between 1970 and 2199, got '1969'",
		"*/0 9 * * *":                      "Invalid cron expression: minute step cannot be 0",
		"0 9 * * 5-1":                      "Invalid cron expression: day of week range '5-1' runs backwards",
		"0 9 L * *":                        "Invalid cron expression: day of month must be between 1 and 31, got 'L'",
		"0 9 * * 1#2":                      "Invalid cron expression: invalid day of week field '1#2'",
		"@daily 0 0 0 0":                   "Invalid cron expression: invalid minute field '@daily'",
	}
	for expr, want := range cases {
		if got := service.CronError(expr); got != want {
			t.Errorf("%q: got %q, want %q", expr, got, want)
		}
	}
}

func TestCheckTimezone(t *testing.T) {
	for _, ok := range []string{"UTC", "Europe/Berlin", "America/New_York"} {
		if err := service.CheckTimezone(ok); err != nil {
			t.Errorf("%s refused: %v", ok, err)
		}
	}
	for _, bad := range []string{"", "Local", "Mars/Olympus"} {
		if err := service.CheckTimezone(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
}
