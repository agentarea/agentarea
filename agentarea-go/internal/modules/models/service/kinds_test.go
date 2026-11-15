package service

import "testing"

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
