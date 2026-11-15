package app

import (
	"testing"

	agentsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	connectionsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

func TestTheCodeToolCatalogueOffersOnlyWhatARunExecutes(t *testing.T) {
	run, err := connectionsservice.CodeToolsets()
	if err != nil {
		t.Fatal(err)
	}
	for _, ts := range (agentsservice.CodeCatalogue{}).Metadata() {
		exec, ok := run[ts.Name]
		if !ok {
			t.Errorf("the editor offers %s, which a run cannot execute", ts.Name)
			continue
		}
		have := map[string]bool{}
		for _, m := range exec.Methods {
			have[m.Method] = true
		}
		for _, m := range ts.Methods {
			if !have[m.Name] {
				t.Errorf("the editor offers %s.%s, which a run cannot execute", ts.Name, m.Name)
			}
		}
	}
}
