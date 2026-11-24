package service

import (
	"context"
	"errors"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	govapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

type fakeAudit struct {
	recs []govapi.AuditRecord
	err  error
}

func (f *fakeAudit) RecordOnce(_ context.Context, _ db.Session, rec govapi.AuditRecord) error {
	f.recs = append(f.recs, rec)
	return f.err
}

type warnings struct{ n int }

func (w *warnings) WarnContext(context.Context, string, ...any) { w.n++ }

func TestAuditCarriesTheCredential(t *testing.T) {
	a := &fakeAudit{}
	s := New(Deps{Audit: a})
	c := authn.Caller{Principal: authn.Principal{UserID: "u1", Credential: &authn.Credential{
		Kind: authn.KindAPIKey, KeyID: "k1", Surface: authn.SurfaceAPI,
	}}}
	s.audit(context.Background(), db.Session{}, c, "agent.archive", "agent", "a1")
	if len(a.recs) != 1 {
		t.Fatal(a.recs)
	}
	r := a.recs[0]
	if r.Action != "agent.archive" || r.ResourceType != "agent" || r.ResourceID != "a1" || r.ActorType != "user" || r.ActorID != "u1" || r.EventID == "" {
		t.Errorf("%+v", r)
	}
	if r.Metadata["credential"] != "api_key" || r.Metadata["surface"] != "api" || r.Metadata["api_key_id"] != "k1" {
		t.Errorf("%v", r.Metadata)
	}
}

func TestAuditFailureIsLoggedNotRaised(t *testing.T) {
	w := &warnings{}
	s := New(Deps{Audit: &fakeAudit{err: errors.New("down")}, Log: w})
	s.audit(context.Background(), db.Session{}, authn.Caller{Principal: authn.Principal{UserID: "u"}}, "agent.create", "agent", "a")
	if w.n != 1 {
		t.Errorf("warnings = %d", w.n)
	}
	New(Deps{}).audit(context.Background(), db.Session{}, authn.Caller{}, "agent.create", "agent", "a")
}
