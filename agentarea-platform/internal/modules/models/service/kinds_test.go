package service

import (
	"reflect"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

func TestModelKind(t *testing.T) {
	e := newEnv(t)
	id := e.instance(e.ws.ID(), e.config(e.ws.ID(), "", nil), e.chat.ID)
	if kind, found, err := e.svc.ModelKind(e.ctx, e.ws, id); err != nil || !found || kind != "chat" {
		t.Fatalf("own instance: %q %v %v", kind, found, err)
	}
	if _, found, err := e.svc.ModelKind(e.ctx, e.other, id); err != nil || found {
		t.Fatalf("another workspace sees it: %v %v", found, err)
	}
	if _, found, err := e.svc.ModelKind(e.ctx, e.ws, "nope"); err != nil || found {
		t.Fatalf("not a uuid: %v %v", found, err)
	}
}

func TestInstanceName(t *testing.T) {
	e := newEnv(t)
	id := e.instance(e.ws.ID(), e.config(e.ws.ID(), "", nil), e.chat.ID)
	got, found, err := e.svc.InstanceName(e.ctx, e.ws, id)
	if err != nil || !found || !reflect.DeepEqual(got, api.InstanceName{ID: id, Name: "i", ModelName: "gpt-x", Kind: "chat"}) {
		t.Fatalf("own instance: %+v %v %v", got, found, err)
	}
	if _, found, err := e.svc.InstanceName(e.ctx, e.other, id); err != nil || found {
		t.Fatalf("another workspace sees it: %v %v", found, err)
	}
	if _, found, err := e.svc.InstanceName(e.ctx, e.ws, "nope"); err != nil || found {
		t.Fatalf("not a uuid: %v %v", found, err)
	}
}

func TestInstanceNameTakesTheModelsReasoningLevelsElseTheProviders(t *testing.T) {
	e := newEnv(t)
	cfg := e.config(e.ws.ID(), "", nil)
	prov := e.cat.providers[e.prov.ID]
	prov.ReasoningEfforts = []string{"low", "high"}
	e.cat.providers[e.prov.ID] = prov
	id := e.instance(e.ws.ID(), cfg, e.chat.ID)
	if got, _, err := e.svc.InstanceName(e.ctx, e.ws, id); err != nil || !reflect.DeepEqual(got.ReasoningLevels, []string{"low", "high"}) {
		t.Fatalf("provider's levels: %+v %v", got, err)
	}
	spec := e.cat.models[e.chat.ID]
	spec.ReasoningEfforts = []string{"minimal"}
	e.cat.models[e.chat.ID] = spec
	if got, _, err := e.svc.InstanceName(e.ctx, e.ws, id); err != nil || !reflect.DeepEqual(got.ReasoningLevels, []string{"minimal"}) {
		t.Fatalf("model's levels: %+v %v", got, err)
	}
}
