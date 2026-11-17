package db

import (
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

func TestLoadConfigRequiresIdentity(t *testing.T) {
	l := config.FromMap(nil)
	LoadConfig(l)
	err := l.Err()
	for _, name := range []string{"AGENTAREA_DB_HOST", "AGENTAREA_DB_NAME", "AGENTAREA_DB_USER", "AGENTAREA_DB_PASSWORD"} {
		if err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("missing %s not reported: %v", name, err)
		}
	}
}

func TestURLs(t *testing.T) {
	l := config.FromMap(map[string]string{
		"AGENTAREA_DB_HOST": "db", "AGENTAREA_DB_NAME": "agentarea", "AGENTAREA_DB_USER": "app",
		"AGENTAREA_DB_PASSWORD": "p@ss/word", "AGENTAREA_DB_SSLMODE": "require", "AGENTAREA_DB_READ_HOST": "replica",
	})
	c := LoadConfig(l)
	if err := l.Err(); err != nil {
		t.Fatal(err)
	}
	if got := c.WriteURL(); got != "postgres://app:p%40ss%2Fword@db:5432/agentarea?sslmode=require" {
		t.Errorf("WriteURL = %s", got)
	}
	if got := c.ReadURL(); !strings.Contains(got, "@replica:5432/") {
		t.Errorf("ReadURL = %s", got)
	}
}
