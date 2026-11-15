package service

import (
	"context"
	"errors"
	"slices"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/domain"
)

func sp(s string) *string { return &s }

func TestRunInstructionsWalkRootFirst(t *testing.T) {
	ctx := context.Background()
	svc, st, ws, _ := setup(t, nil)
	root, _ := svc.Create(ctx, ws, "u", domain.New{Name: `R&"D'`, Instructions: sp("  root rules \n")})
	mid, _ := svc.Create(ctx, ws, "u", domain.New{Name: "Mid", Instructions: sp("   "), ParentProjectID: &root.ID})
	leaf, _ := svc.Create(ctx, ws, "u", domain.New{Name: "Leaf", Instructions: sp("leaf rules"), ParentProjectID: &mid.ID})

	chain, err := svc.Chain(ctx, ws, uuid.NewString(), leaf.ID)
	if err != nil {
		t.Fatal(err)
	}
	want := []api.Instruction{{Name: `R&"D'`, Text: "root rules"}, {Name: "Leaf", Text: "leaf rules"}}
	if !slices.Equal(chain, want) {
		t.Fatalf("chain %+v", chain)
	}
	blocks, err := svc.Blocks(ctx, ws, uuid.NewString(), leaf.ID)
	if err != nil {
		t.Fatal(err)
	}
	if blocks[0] != "<project name=\"R&amp;&quot;D&#x27;\">\nroot rules\n</project>" || blocks[1] != "<project name=\"Leaf\">\nleaf rules\n</project>" {
		t.Fatalf("blocks %q", blocks)
	}

	// A cycle written around the check ends the walk instead of looping.
	r := st.rows[uuid.MustParse(root.ID)]
	r.p.ParentProjectID = &leaf.ID
	st.rows[uuid.MustParse(root.ID)] = r
	if chain, err = svc.Chain(ctx, ws, uuid.NewString(), leaf.ID); err != nil || len(chain) != 2 {
		t.Fatalf("cycle chain %+v %v", chain, err)
	}
}

func TestRunInstructionsFromTheAgentsOnlyProject(t *testing.T) {
	ctx := context.Background()
	svc, st, ws, other := setup(t, nil)
	agent := uuid.New()
	one, _ := svc.Create(ctx, ws, "u", domain.New{Name: "One", Instructions: sp("one")})
	two, _ := svc.Create(ctx, ws, "u", domain.New{Name: "Two", Instructions: sp("two")})
	foreign, _ := svc.Create(ctx, other, "u", domain.New{Name: "F", Instructions: sp("foreign")})
	link := func(p domain.Project) {
		_ = st.Link(ctx, db.NewSession(ws, nil), domain.LinkAgent, uuid.MustParse(p.ID), agent)
	}

	link(one)
	link(foreign)
	chain, err := svc.Chain(ctx, ws, agent.String(), "")
	if err != nil || len(chain) != 1 || chain[0].Text != "one" {
		t.Fatalf("only project %+v %v", chain, err)
	}

	link(two)
	if chain, err = svc.Chain(ctx, ws, agent.String(), ""); err != nil || len(chain) != 0 {
		t.Fatalf("several projects %+v %v", chain, err)
	}
}

func TestRunInstructionsRefuseAMalformedProject(t *testing.T) {
	svc, _, ws, other := setup(t, nil)
	ctx := context.Background()
	if _, err := svc.Chain(ctx, ws, uuid.NewString(), "not-a-uuid"); !errors.Is(err, api.ErrInvalidProject) {
		t.Fatalf("got %v", err)
	}
	foreign, _ := svc.Create(ctx, other, "u", domain.New{Name: "F", Instructions: sp("x")})
	if chain, err := svc.Chain(ctx, ws, uuid.NewString(), foreign.ID); err != nil || len(chain) != 0 {
		t.Fatalf("foreign project %+v %v", chain, err)
	}
}
