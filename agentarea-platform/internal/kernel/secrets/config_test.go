package secrets

import (
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
)

func load(vars map[string]string) (Config, error) {
	l := config.FromMap(vars)
	c := LoadConfig(l)
	return c, l.Err()
}

func TestConfigDatabaseDefault(t *testing.T) {
	c, err := load(map[string]string{"AGENTAREA_SECRET_ENCRYPTION_KEY": pyKey})
	if err != nil || c.Backend != BackendDatabase || c.Env != "prod" {
		t.Fatalf("%+v %v", c, err)
	}
}

func TestConfigFailsLoud(t *testing.T) {
	for name, tc := range map[string]struct {
		vars map[string]string
		want string
	}{
		"no key":        {nil, "AGENTAREA_SECRET_ENCRYPTION_KEY"},
		"bad key":       {map[string]string{"AGENTAREA_SECRET_ENCRYPTION_KEY": "nope"}, "AGENTAREA_SECRET_ENCRYPTION_KEY"},
		"bad backend":   {map[string]string{"AGENTAREA_SECRET_BACKEND": "vault"}, "AGENTAREA_SECRET_BACKEND"},
		"infisical":     {map[string]string{"AGENTAREA_SECRET_BACKEND": "Infisical"}, "AGENTAREA_SECRET_CLIENT_ID"},
		"infisical pid": {map[string]string{"AGENTAREA_SECRET_BACKEND": "infisical", "AGENTAREA_SECRET_CLIENT_ID": "a", "AGENTAREA_SECRET_CLIENT_SECRET": "b"}, "AGENTAREA_SECRET_PROJECT_ID"},
	} {
		_, err := load(tc.vars)
		if err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: %v", name, err)
		}
		if err != nil && strings.Contains(err.Error(), "nope") && name == "bad key" {
			t.Errorf("error repeats the key")
		}
	}
	c, err := load(map[string]string{"AGENTAREA_SECRET_BACKEND": "INFISICAL", "AGENTAREA_SECRET_CLIENT_ID": "a", "AGENTAREA_SECRET_CLIENT_SECRET": "b", "AGENTAREA_SECRET_PROJECT_ID": "p"})
	if err != nil || c.Endpoint != DefaultInfisicalEndpoint {
		t.Errorf("%+v %v", c, err)
	}
}
