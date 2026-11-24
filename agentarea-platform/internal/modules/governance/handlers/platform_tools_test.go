package handlers

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

func TestPlatformToolsRefuseANonAdmin(t *testing.T) {
	deny := PlatformTools{Admin: func(context.Context, authn.Caller) error { return authz.ErrNotWorkspaceAdmin }}
	ctx, c := context.Background(), authn.Caller{}
	for name, call := range map[string]func() error{
		"list":   func() error { _, err := deny.ListRules(ctx, c, api.PolicyRuleFilter{}); return err },
		"get":    func() error { _, err := deny.GetRule(ctx, c, "r"); return err },
		"create": func() error { _, err := deny.CreateRule(ctx, c, []byte(`{}`)); return err },
		"update": func() error { _, err := deny.UpdateRule(ctx, c, "r", []byte(`{}`)); return err },
		"delete": func() error { return deny.DeleteRule(ctx, c, "r") },
		"audit":  func() error { _, err := deny.List(ctx, c, api.PlatformAuditQuery{}); return err },
		"secret": func() error { _, err := deny.Create(ctx, c, "n", "v", nil); return err },
		"forget": func() error { return deny.DeleteByName(ctx, c, "n") },
	} {
		if err := call(); !errors.Is(err, authz.ErrNotWorkspaceAdmin) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestPlatformPoliciesListValidatesEnums(t *testing.T) {
	allow := PlatformTools{Admin: func(context.Context, authn.Caller) error { return nil }}
	bad := "robot"
	_, err := allow.ListRules(context.Background(), authn.Caller{}, api.PolicyRuleFilter{SubjectType: &bad, Effect: &bad})
	if err == nil || !strings.HasPrefix(err.Error(), "2 validation errors for listArguments\nsubject_type\n  Input should be ") {
		t.Fatalf("%v", err)
	}
}
