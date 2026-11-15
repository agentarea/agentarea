package service

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
)

// connectionSecrets reads secret names of a connection: from the platform
// workspace for a platform-managed one (the only one that writes them),
// else from ws. An absent value is "".
func (s *Service) connectionSecretValues(ctx context.Context, ws scope.Workspace, userID string, conn domain.Connection, names []string) (map[string]string, error) {
	out := map[string]string{}
	if len(names) == 0 {
		return out, nil
	}
	if conn.PlatformManaged() {
		ws, userID = PlatformWorkspace(), PlatformWorkspaceID
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	m := s.d.Secrets.Manager(sess, userID)
	for _, n := range names {
		v, err := m.Get(ctx, n)
		if errors.Is(err, ksecrets.ErrNotFound) {
			continue
		}
		if err != nil {
			return nil, err
		}
		out[n] = v
	}
	return out, nil
}

// connectionHeaders is resolve_headers: the custom headers with their secret
// values, then the linked auth config's headers, which win. The result
// carries credentials.
func (s *Service) connectionHeaders(ctx context.Context, ws scope.Workspace, userID string, conn domain.Connection) (map[string]string, error) {
	var names []string
	for _, h := range conn.CustomHeaders {
		if h.Secret {
			names = append(names, domain.SecretHeaderKey(conn.ID, h.Name))
		}
	}
	values, err := s.connectionSecretValues(ctx, ws, userID, conn, names)
	if err != nil {
		return nil, err
	}
	headers := map[string]string{}
	for _, h := range conn.CustomHeaders {
		if h.Secret {
			v := values[domain.SecretHeaderKey(conn.ID, h.Name)]
			if v == "" {
				return nil, &domain.Invalid{Msg: fmt.Sprintf("Connection %s has no stored value for header '%s'. Re-enter it.", conn.ID, h.Name)}
			}
			headers[h.Name] = v
			continue
		}
		if h.Value != nil && *h.Value != "" {
			headers[h.Name] = *h.Value
		}
	}
	if conn.AuthConfigID == nil {
		return headers, nil
	}
	origin := openapispec.Origin(conn.BaseURL)
	if len(conn.AllowedAuthOrigins) > 0 && !slices.Contains(conn.AllowedAuthOrigins, origin) {
		return nil, &domain.Invalid{Msg: fmt.Sprintf("Connection %s cannot send OAuth credentials to origin '%s'.", conn.ID, origin)}
	}
	authID, err := uuid.Parse(*conn.AuthConfigID)
	if err != nil {
		return nil, err
	}
	authWS := ws
	if conn.PlatformManaged() {
		authWS = PlatformWorkspace()
	}
	auth, err := s.AuthHeaders(ctx, authWS, authID, origin, false)
	if err != nil {
		return nil, err
	}
	for k, v := range auth {
		for existing := range headers {
			if strings.EqualFold(existing, k) && existing != k {
				delete(headers, existing)
			}
		}
		headers[k] = v
	}
	return headers, nil
}

// connectionBaseURL is resolve_base_url: the placeholders filled with their
// URL-encoded secret values. The result carries credentials.
func (s *Service) connectionBaseURL(ctx context.Context, ws scope.Workspace, userID string, conn domain.Connection) (string, error) {
	names := make([]string, len(conn.URLVariables))
	for i, v := range conn.URLVariables {
		names[i] = domain.SecretURLVarKey(conn.ID, v)
	}
	values, err := s.connectionSecretValues(ctx, ws, userID, conn, names)
	if err != nil {
		return "", err
	}
	base := conn.BaseURL
	for _, v := range conn.URLVariables {
		value := values[domain.SecretURLVarKey(conn.ID, v)]
		if value == "" {
			return "", &domain.Invalid{Msg: fmt.Sprintf("Connection %s has no stored value for URL variable '%s'. Re-enter it.", conn.ID, v)}
		}
		base = strings.ReplaceAll(base, "{"+v+"}", openapispec.QuoteAll(value))
	}
	return base, nil
}

// connectionQuery is resolve_query_params. The result carries credentials.
func (s *Service) connectionQuery(ctx context.Context, ws scope.Workspace, userID string, conn domain.Connection) (map[string]string, error) {
	var names []string
	for _, p := range conn.CustomQuery {
		if p.Secret {
			names = append(names, domain.SecretQueryKey(conn.ID, p.Name))
		}
	}
	values, err := s.connectionSecretValues(ctx, ws, userID, conn, names)
	if err != nil {
		return nil, err
	}
	out := map[string]string{}
	for _, p := range conn.CustomQuery {
		if !p.Secret {
			v := ""
			if p.Value != nil {
				v = *p.Value
			}
			out[p.Name] = v
			continue
		}
		v := values[domain.SecretQueryKey(conn.ID, p.Name)]
		if v == "" {
			return nil, &domain.Invalid{Msg: fmt.Sprintf("Connection %s has no stored value for query parameter '%s'. Re-enter it.", conn.ID, p.Name)}
		}
		out[p.Name] = v
	}
	return out, nil
}
