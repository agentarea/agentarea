package service

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
)

// The platform workspace and principal the operator writes as, and the header its token rides.
const (
	platformWorkspace = "platform"
	platformPrincipal = "platform"
	platformAuth      = "Authorization"
)

var _ api.PlatformConnections = (*Service)(nil)

// DeclareMCP implements api.PlatformConnections.
func (s *Service) DeclareMCP(ctx context.Context, d api.DeclaredMCP) error {
	ws, err := scope.NewWorkspace(platformWorkspace, "")
	if err != nil {
		return err
	}
	jsonSpec, err := json.Marshal(map[string]any{"env_vars": []string{platformAuth}})
	if err != nil {
		return err
	}
	var verification []byte
	if d.EndpointChanged {
		if verification, err = json.Marshal(domain.DefaultVerification()); err != nil {
			return err
		}
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		if err := (store.Platform{}).DeclareMCP(ctx, sess, d, jsonSpec, verification, platformPrincipal, time.Now()); err != nil {
			return err
		}
		return putSecret(ctx, s.d.Secrets.Manager(sess, platformPrincipal),
			domain.InstanceSecretName(d.InstanceID.String(), platformAuth), "Bearer "+strings.TrimSpace(d.Token))
	})
}

// DeclareOpenAPI implements api.PlatformConnections: the spec is fetched outside the transaction.
func (s *Service) DeclareOpenAPI(ctx context.Context, d api.DeclaredOpenAPI) error {
	ws, err := scope.NewWorkspace(platformWorkspace, "")
	if err != nil {
		return err
	}
	doc, err := s.fetchSpec(ctx, d.SpecURL, nil)
	if err != nil {
		return err
	}
	tools, err := openapispec.ParseSpec(doc, nil)
	if err != nil {
		return err
	}
	spec, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	headers, err := json.Marshal([]map[string]any{{"name": platformAuth, "secret": true, "value": nil}})
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		if err := (store.Platform{}).DeclareOpenAPI(ctx, sess, d, spec, toolsJSON(tools), headers, platformPrincipal, time.Now()); err != nil {
			return err
		}
		return putSecret(ctx, s.d.Secrets.Manager(sess, platformPrincipal),
			domain.SecretHeaderKey(d.ID.String(), platformAuth), "Bearer "+strings.TrimSpace(d.Token))
	})
}

// putSecret sets name to value unless it already holds it; a value the key cannot open is rewritten.
func putSecret(ctx context.Context, m ksecrets.Manager, name, value string) error {
	current, err := m.Get(ctx, name)
	switch {
	case err == nil && current == value:
		return nil
	case errors.Is(err, ksecrets.ErrDecrypt):
		slog.WarnContext(ctx, "A declared secret does not decrypt with the current key; rewriting it", "secret_name", name)
	case err != nil && !errors.Is(err, ksecrets.ErrNotFound):
		return err
	}
	return m.Set(ctx, name, value)
}
