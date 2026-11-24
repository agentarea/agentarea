package config

import (
	"errors"
	"strings"
	"testing"
	"time"
)

func TestParseDurationMatchesPython(t *testing.T) {
	ok := map[string]time.Duration{
		"30s": 30 * time.Second, "500ms": 500 * time.Millisecond, "5m": 5 * time.Minute,
		"2h": 2 * time.Hour, "7d": 7 * 24 * time.Hour, "1.5h": 90 * time.Minute, " 10s ": 10 * time.Second,
	}
	for in, want := range ok {
		got, err := ParseDuration(in)
		if err != nil || got != want {
			t.Errorf("ParseDuration(%q) = %v, %v; want %v", in, got, err, want)
		}
	}
	for _, in := range []string{"30", "1h30m", "s", ".5s", "5.s", "-1s", "1us", "1 s"} {
		if _, err := ParseDuration(in); err == nil {
			t.Errorf("ParseDuration(%q) accepted", in)
		}
	}
}

func TestParseBool(t *testing.T) {
	for _, v := range []string{"1", "TRUE", "t", "Yes", "y", "on"} {
		if b, err := ParseBool(v); err != nil || !b {
			t.Errorf("ParseBool(%q) = %v, %v", v, b, err)
		}
	}
	for _, v := range []string{"0", "false", "F", "no", "n", "OFF"} {
		if b, err := ParseBool(v); err != nil || b {
			t.Errorf("ParseBool(%q) = %v, %v", v, b, err)
		}
	}
	if _, err := ParseBool("maybe"); err == nil {
		t.Error("ParseBool(maybe) accepted")
	}
}

func TestLoaderCollectsEveryFailure(t *testing.T) {
	l := FromMap(map[string]string{
		"AGENTAREA_DB_PORT":         "x",
		"AGENTAREA_OTEL_ENABLED":    "maybe",
		"AGENTAREA_STARTUP_TIMEOUT": "30",
		"AGENTAREA_DB_HOST":         "  ",
	})
	l.RequiredEnv("AGENTAREA_DB_HOST")
	l.IntEnv("AGENTAREA_DB_PORT", 5432)
	l.BoolEnv("AGENTAREA_OTEL_ENABLED", false)
	l.DurationEnv("AGENTAREA_STARTUP_TIMEOUT", time.Second)
	err := l.Err()
	if err == nil {
		t.Fatal("want errors")
	}
	if !errors.Is(err, ErrMissing) {
		t.Error("missing variable not reported as ErrMissing")
	}
	for _, name := range []string{"AGENTAREA_DB_HOST", "AGENTAREA_DB_PORT", "AGENTAREA_OTEL_ENABLED", "AGENTAREA_STARTUP_TIMEOUT"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error does not name %s: %v", name, err)
		}
	}
}

func TestLoadCommonDefaultsAndValidation(t *testing.T) {
	l := FromMap(nil)
	c := LoadCommon(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if c.Env != "development" || c.Edition != "oss" || c.LogLevel != "INFO" || c.LogFormat != "json" ||
		c.OTelEnabled || c.StartupTimeout != 120*time.Second || c.ShutdownTimeout != 30*time.Second {
		t.Fatalf("unexpected defaults %+v", c)
	}
	l = FromMap(map[string]string{"AGENTAREA_LOG_LEVEL": "debug", "AGENTAREA_EDITION": "pro", "AGENTAREA_SHUTDOWN_TIMEOUT": "0s"})
	c = LoadCommon(l)
	if c.LogLevel != "DEBUG" {
		t.Errorf("LogLevel = %q", c.LogLevel)
	}
	err := l.Err()
	if err == nil || !strings.Contains(err.Error(), "AGENTAREA_EDITION") || !strings.Contains(err.Error(), "AGENTAREA_SHUTDOWN_TIMEOUT") {
		t.Fatalf("want edition and shutdown errors, got %v", err)
	}
}

func TestListEnv(t *testing.T) {
	l := FromMap(map[string]string{"AGENTAREA_CORS_ORIGINS": " a, ,b ,"})
	got := l.ListEnv("AGENTAREA_CORS_ORIGINS", nil)
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Fatalf("got %q", got)
	}
}
