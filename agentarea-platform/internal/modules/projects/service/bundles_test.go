package service

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/domain"
)

func TestBundleProjectsLinkAndUnlinkWhatTheDeployManages(t *testing.T) {
	ctx := context.Background()
	a1, a2, mine, skill := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	svc, st, ws, _ := setup(t, map[string]string{a1: "One", a2: "Two", mine: "Mine", skill: "Notes"})
	c := authn.Caller{Principal: authn.Principal{UserID: "u"}, Workspace: ws}
	b := BundleProjects{S: svc}
	desc := "Inbound"
	id, err := b.CreateProject(ctx, c, catalogapi.BundleProjectSpec{Name: "Support", Description: &desc, AgentIDs: []string{a1, a2}, SkillIDs: []string{skill}})
	if err != nil {
		t.Fatal(err)
	}
	if name, ok, err := b.ProjectName(ctx, c, id); !ok || err != nil || name != "Support" {
		t.Fatalf("name = %q %v %v", name, ok, err)
	}
	if err := svc.Link(ctx, ws, domain.LinkAgent, uuid.MustParse(id), mine); err != nil {
		t.Fatal(err)
	}
	managed := catalogapi.BundleProjectSpec{Name: "Support", AgentIDs: []string{a1, a2}, SkillIDs: []string{skill}}
	instructions := "Be kind"
	if err := b.UpdateProject(ctx, c, id, catalogapi.BundleProjectSpec{Name: "Help", Instructions: &instructions, AgentIDs: []string{a1}}, managed); err != nil {
		t.Fatal(err)
	}
	p, err := svc.Get(ctx, ws, uuid.MustParse(id))
	if err != nil || p.Name != "Help" || p.Description != nil || *p.Instructions != "Be kind" {
		t.Fatalf("project = %+v, %v", p, err)
	}
	l := st.links[id]
	if !reflect.DeepEqual(l.Agents, []string{a1, mine}) || len(l.Skills) != 0 {
		t.Fatalf("links = %+v (the agent linked by hand stays)", l)
	}
	_, err = b.CreateProject(ctx, c, catalogapi.BundleProjectSpec{Name: "Ghost", AgentIDs: []string{uuid.NewString()}})
	var refusal *catalogapi.BundleRefusal
	if !errors.As(err, &refusal) || refusal.Msg != "Agent not found" || len(st.rows) != 1 {
		t.Fatalf("err = %v, rows = %d (a refused create leaves nothing)", err, len(st.rows))
	}
	if err := b.DeleteProject(ctx, c, id); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := b.ProjectName(ctx, c, id); ok || err != nil {
		t.Fatalf("after delete: %v %v", ok, err)
	}
}
