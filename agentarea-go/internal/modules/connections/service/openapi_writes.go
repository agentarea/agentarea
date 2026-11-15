package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
)

// OpenAPIWriteStore is the openapi_connections writes and full reads (store.OpenAPI).
type OpenAPIWriteStore interface {
	Insert(ctx context.Context, s db.Session, n store.ConnectionNew) (domain.Connection, error)
	Full(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error)
	Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error)
	Save(ctx context.Context, s db.Session, id uuid.UUID, r store.ConnectionRow) (bool, error)
	SetDiscovery(ctx context.Context, s db.Session, id uuid.UUID, tools, spec json.RawMessage, now time.Time) (bool, error)
	SetLastDispatch(ctx context.Context, s db.Session, id uuid.UUID, dispatch map[string]any) (bool, error)
}

// HeaderIn is one custom header as given (HeaderInput, validated).
type HeaderIn struct{ Name, Value string }

// QueryIn is one query parameter as given (QueryParamInput, validated).
type QueryIn struct {
	Name   string
	Secret bool
	Value  string
}

// VarIn is one URL variable as given (UrlVariableInput, validated).
type VarIn struct{ Name, Value string }

// ConnectionCreate is OpenAPIConnectionCreate, validated. SpecContent is the
// document as given (wirejson objects keep its key order); nil is none.
type ConnectionCreate struct {
	Name         string
	BaseURL      string
	Description  *string
	SpecURL      *string
	SpecContent  any
	AuthConfigID *uuid.UUID
	Headers      []HeaderIn
	Query        []QueryIn
	URLVariables []VarIn
}

// ConnectionPatch is OpenAPIConnectionUpdate: a *Set flag marks a field the
// body carried. Headers, Query and URLVariables are set only when not null.
type ConnectionPatch struct {
	NameSet         bool
	Name            string
	DescriptionSet  bool
	Description     *string
	BaseURLSet      bool
	BaseURL         string
	SpecURLSet      bool
	SpecURL         *string
	SpecContentSet  bool
	SpecContent     any
	AuthConfigSet   bool
	AuthConfigID    *uuid.UUID
	HeadersSet      bool
	Headers         []HeaderIn
	QuerySet        bool
	Query           []QueryIn
	URLVariablesSet bool
	URLVariables    []VarIn
	CostSet         bool
	Cost            map[string]any
}

// Empty is a body with no field set ("No fields to update").
func (p ConnectionPatch) Empty() bool {
	return !p.NameSet && !p.DescriptionSet && !p.BaseURLSet && !p.SpecURLSet && !p.SpecContentSet &&
		!p.AuthConfigSet && !p.HeadersSet && !p.QuerySet && !p.URLVariablesSet && !p.CostSet
}

// safeHeaders are never sensitive: stored in the row in plain text.
func safeHeaders() map[string]bool {
	return map[string]bool{
		"accept": true, "accept-charset": true, "accept-encoding": true, "accept-language": true,
		"cache-control": true, "content-type": true, "if-match": true, "if-none-match": true,
		"user-agent": true, "x-correlation-id": true, "x-request-id": true,
	}
}

// OpenAPIWritesReady reports the ports the OpenAPI writes need.
func (s *Service) OpenAPIWritesReady() bool {
	return s.d.OpenAPIWrites != nil && s.d.Out != nil && s.d.Secrets != nil && s.d.Graph != nil
}

// CatalogConnectReady reports the catalog item read the from-catalog routes need.
func (s *Service) CatalogConnectReady() bool {
	return s.d.CatalogItems != nil && s.OpenAPIWritesReady()
}

func invalid(err error) error {
	var pe *openapispec.Error
	if errors.As(err, &pe) {
		return &domain.Invalid{Msg: pe.Msg}
	}
	return err
}

// checkURL is validate_url with the deployment's policy: a refusal is a 400.
func (s *Service) checkURL(ctx context.Context, u string) error {
	if _, err := s.d.Out.Guard().CheckURL(ctx, u); err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			return &domain.Invalid{Msg: openapispec.UnsafeMessage(err)}
		}
		return err
	}
	return nil
}

// specClient fetches a spec: pinned for dest, 30 s, redirects not followed.
func (s *Service) specClient(dest netguard.Destination) *http.Client {
	return &http.Client{
		Transport:     s.d.Out.Transport(dest),
		Timeout:       openapispec.FetchTimeout * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}

func (s *Service) fetchSpec(ctx context.Context, u string, headers map[string]string) (any, error) {
	if err := s.checkURL(ctx, u); err != nil {
		return nil, err
	}
	spec, err := openapispec.Fetch(ctx, s.specClient(netguard.Member), u, headers)
	return spec, invalid(err)
}

func configuredQuery(ps []domain.QueryParam) map[string]bool {
	out := map[string]bool{}
	for _, p := range ps {
		out[p.Name] = true
	}
	return out
}

func toolsJSON(tools []openapispec.Tool) json.RawMessage {
	out := make([]wirejson.Object, len(tools))
	for i, t := range tools {
		out[i] = wirejson.Object{{Key: "name", Value: t.Name}, {Key: "description", Value: t.Description}, {Key: "inputSchema", Value: t.InputSchema}}
	}
	raw, err := json.Marshal(out)
	if err != nil {
		panic(err)
	}
	return raw
}

func storedToolsJSON(tools []domain.Tool) json.RawMessage {
	out := make([]wirejson.Object, len(tools))
	for i, t := range tools {
		var schema any
		if t.InputSchema != nil {
			schema = t.InputSchema
		}
		out[i] = wirejson.Object{{Key: "name", Value: t.Name}, {Key: "description", Value: t.Description}, {Key: "inputSchema", Value: schema}}
	}
	raw, err := json.Marshal(out)
	if err != nil {
		panic(err)
	}
	return raw
}

func specJSON(spec any) (json.RawMessage, error) {
	if spec == nil {
		return nil, nil
	}
	return json.Marshal(spec)
}

func varNames(vs []VarIn) []string {
	out := make([]string, len(vs))
	for i, v := range vs {
		out[i] = v.Name
	}
	return out
}

// checkQuerySecrets is _store_query_params' check: a secret parameter
// with no value keeps one already stored, else it is refused.
func checkQuerySecrets(in []QueryIn, kept map[string]bool) error {
	for _, p := range in {
		if p.Secret && p.Value == "" && !kept[p.Name] {
			return &domain.Invalid{Msg: fmt.Sprintf("Secret query parameter '%s' needs a value.", p.Name)}
		}
	}
	return nil
}

func queryRow(in []QueryIn) []domain.QueryParam {
	out := make([]domain.QueryParam, 0, len(in))
	for _, p := range in {
		q := domain.QueryParam{Name: p.Name, Secret: p.Secret}
		if !p.Secret {
			v := p.Value
			q.Value = &v
		}
		out = append(out, q)
	}
	return out
}

// headerRow is _store_headers' classification: a header that is not safe
// is a secret, and a secret with no value is dropped.
func headerRow(in []HeaderIn) []domain.Header {
	out := make([]domain.Header, 0, len(in))
	for _, h := range in {
		name := strings.TrimSpace(h.Name)
		if name == "" {
			continue
		}
		if !safeHeaders()[strings.ToLower(name)] {
			if h.Value == "" {
				continue
			}
			out = append(out, domain.Header{Name: name, Secret: true})
			continue
		}
		v := h.Value
		out = append(out, domain.Header{Name: name, Value: &v})
	}
	return out
}

// secretWrite is one value a write stores under a connection's secret name.
type secretWrite struct{ name, value string }

func connectionSecrets(id string, headers []HeaderIn, query []QueryIn, vars []VarIn) []secretWrite {
	var out []secretWrite
	for _, h := range headers {
		name := strings.TrimSpace(h.Name)
		if name != "" && !safeHeaders()[strings.ToLower(name)] && h.Value != "" {
			out = append(out, secretWrite{domain.SecretHeaderKey(id, name), h.Value})
		}
	}
	for _, p := range query {
		if p.Secret && p.Value != "" {
			out = append(out, secretWrite{domain.SecretQueryKey(id, p.Name), p.Value})
		}
	}
	for _, v := range vars {
		out = append(out, secretWrite{domain.SecretURLVarKey(id, v.Name), v.Value})
	}
	return out
}

func setSecrets(ctx context.Context, m ksecrets.Manager, writes []secretWrite, written *[]string) error {
	for _, w := range writes {
		if err := m.Set(ctx, w.name, w.value); err != nil {
			return err
		}
		*written = append(*written, w.name)
	}
	return nil
}

// dropSecrets removes the values a failed write stored outside its
// transaction (a backend that keeps values elsewhere than the database).
func (s *Service) dropSecrets(ctx context.Context, c authn.Caller, names []string) {
	if len(names) == 0 {
		return
	}
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		m := s.d.Secrets.Manager(sess, c.UserID)
		for _, n := range names {
			if _, err := m.Delete(ctx, n); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		s.d.Log.ErrorContext(ctx, "could not remove the secrets of a connection that was not written",
			"workspace_id", c.Workspace.ID(), "secrets", len(names), "error", err)
	}
}

func (s *Service) graphWriter() (authz.Writer, error) {
	w, ok := s.d.Graph.(authz.Writer)
	if !ok {
		return nil, errNoGraphWriter
	}
	return w, nil
}

// CreateConnection is create_connection: every check, the spec fetch and
// its parse come first; the row, its secrets and its owner grant (personal
// to its creator) are then written in one transaction.
func (s *Service) CreateConnection(ctx context.Context, c authn.Caller, in ConnectionCreate, registryItemID *uuid.UUID) (ConnectionView, error) {
	if err := openapispec.CheckURLVariables(in.BaseURL, varNames(in.URLVariables)); err != nil {
		return ConnectionView{}, invalid(err)
	}
	if err := s.checkURL(ctx, in.BaseURL); err != nil {
		return ConnectionView{}, err
	}
	if in.SpecURL != nil {
		if err := s.checkURL(ctx, *in.SpecURL); err != nil {
			return ConnectionView{}, err
		}
	}
	if in.AuthConfigID != nil {
		if err := s.read(ctx, c, func(sess db.Session) error {
			_, err := s.GetAuthConfigForUse(ctx, sess, c, *in.AuthConfigID)
			return err
		}); err != nil {
			return ConnectionView{}, err
		}
	}
	if err := checkQuerySecrets(in.Query, nil); err != nil {
		return ConnectionView{}, err
	}
	var headers []domain.Header
	if len(in.Headers) > 0 {
		headers = headerRow(in.Headers)
	}
	var query []domain.QueryParam
	if len(in.Query) > 0 {
		query = queryRow(in.Query)
	}
	var vars []string
	if len(in.URLVariables) > 0 {
		vars = varNames(in.URLVariables)
	}
	spec := in.SpecContent
	if spec == nil && in.SpecURL != nil && *in.SpecURL != "" {
		plain := map[string]string{}
		for _, h := range headers {
			if !h.Secret && h.Value != nil && *h.Value != "" {
				plain[h.Name] = *h.Value
			}
		}
		var err error
		if spec, err = s.fetchSpec(ctx, *in.SpecURL, plain); err != nil {
			return ConnectionView{}, err
		}
	}
	var tools []openapispec.Tool
	if spec != nil {
		var err error
		if tools, err = openapispec.ParseSpec(spec, configuredQuery(query)); err != nil {
			return ConnectionView{}, invalid(err)
		}
	}
	rawSpec, err := specJSON(spec)
	if err != nil {
		return ConnectionView{}, &domain.Invalid{Msg: err.Error()}
	}
	w, err := s.graphWriter()
	if err != nil {
		return ConnectionView{}, err
	}
	id := s.d.NewID()
	var conn domain.Connection
	var written []string
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		var err error
		conn, err = s.d.OpenAPIWrites.Insert(ctx, sess, store.ConnectionNew{
			ID: id, CreatedBy: c.UserID, Name: in.Name, Description: in.Description, SpecURL: in.SpecURL,
			SpecContent: rawSpec, BaseURL: in.BaseURL, AuthConfigID: in.AuthConfigID, RegistryItemID: registryItemID,
			CustomHeaders: headers, CustomQuery: query, URLVariables: vars, AvailableTools: toolsJSON(tools),
			Status: "active", Now: s.d.Now(),
		})
		if err != nil {
			return err
		}
		m := s.d.Secrets.Manager(sess, c.UserID)
		if err := setSecrets(ctx, m, connectionSecrets(id.String(), in.Headers, in.Query, in.URLVariables), &written); err != nil {
			return err
		}
		if err := authz.GrantResourceOwner(ctx, w, id.String(), c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
			return err
		}
		return authz.MakePersonal(ctx, w, id.String())
	})
	if err != nil {
		s.dropSecrets(ctx, c, written)
		return ConnectionView{}, err
	}
	return ConnectionView{Connection: conn, Sharing: domain.Sharing{Personal: true, IsOwner: conn.CreatedBy == c.UserID}}, nil
}

// UpdateConnection is update_connection with every check made before the
// first write: a refused field leaves the row and its secrets as they were.
func (s *Service) UpdateConnection(ctx context.Context, c authn.Caller, id uuid.UUID, p ConnectionPatch) (ConnectionView, error) {
	var written []string
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		cur, ok, err := s.d.OpenAPIWrites.Lock(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrConnectionNotFound()
		}
		base := cur.BaseURL
		if p.BaseURLSet {
			base = p.BaseURL
		}
		if p.BaseURLSet || p.URLVariablesSet {
			names := cur.URLVariables
			if p.URLVariablesSet {
				names = varNames(p.URLVariables)
			}
			if err := openapispec.CheckURLVariables(base, names); err != nil {
				return invalid(err)
			}
		}
		storedSecretQuery := map[string]bool{}
		for _, q := range cur.CustomQuery {
			if q.Secret {
				storedSecretQuery[q.Name] = true
			}
		}
		if p.QuerySet {
			if err := checkQuerySecrets(p.Query, storedSecretQuery); err != nil {
				return err
			}
		}
		if p.AuthConfigSet && p.AuthConfigID != nil {
			if _, err := s.GetAuthConfigForUse(ctx, sess, c, *p.AuthConfigID); err != nil {
				return err
			}
		}
		if p.BaseURLSet {
			if err := s.checkURL(ctx, p.BaseURL); err != nil {
				return err
			}
			if len(cur.AllowedAuthOrigins) > 0 && !slices.Contains(cur.AllowedAuthOrigins, openapispec.Origin(p.BaseURL)) {
				return &domain.Invalid{Msg: "Catalog OAuth connections cannot be pointed at a different API origin."}
			}
			if parseUUIDPtr(cur.AuthConfigID) != nil && !p.AuthConfigSet {
				if _, err := s.GetAuthConfigForUse(ctx, sess, c, *parseUUIDPtr(cur.AuthConfigID)); err != nil {
					return err
				}
			}
		}
		if p.SpecURLSet && p.SpecURL != nil && *p.SpecURL != "" {
			if err := s.checkURL(ctx, *p.SpecURL); err != nil {
				return err
			}
		}
		row := store.ConnectionRow{
			Name: cur.Name, Description: cur.Description, SpecURL: cur.SpecURL, BaseURL: base,
			AuthConfigID: parseUUIDPtr(cur.AuthConfigID), CustomHeaders: cur.CustomHeaders, CustomQuery: cur.CustomQuery,
			URLVariables: cur.URLVariables, AvailableTools: storedToolsJSON(cur.AvailableTools), Cost: cur.Cost, Now: s.d.Now(),
		}
		spec := cur.SpecContent
		if p.SpecContentSet {
			spec = p.SpecContent
		}
		if p.QuerySet {
			row.CustomQuery = queryRow(p.Query)
		}
		if (p.QuerySet || p.SpecContentSet) && spec != nil {
			tools, err := openapispec.ParseSpec(spec, configuredQuery(row.CustomQuery))
			if err != nil {
				return invalid(err)
			}
			row.AvailableTools = toolsJSON(tools)
		}
		if row.SpecContent, err = specJSON(spec); err != nil {
			return &domain.Invalid{Msg: err.Error()}
		}
		if p.NameSet {
			row.Name = p.Name
		}
		if p.DescriptionSet {
			row.Description = p.Description
		}
		if p.SpecURLSet {
			row.SpecURL = p.SpecURL
		}
		if p.AuthConfigSet {
			row.AuthConfigID = p.AuthConfigID
		}
		if p.CostSet {
			row.Cost = p.Cost
		}

		m := s.d.Secrets.Manager(sess, c.UserID)
		var drop []string
		var writes []secretWrite
		if p.QuerySet {
			still := map[string]bool{}
			for _, q := range p.Query {
				if q.Secret {
					still[q.Name] = true
				}
			}
			for name := range storedSecretQuery {
				if !still[name] {
					drop = append(drop, domain.SecretQueryKey(cur.ID, name))
				}
			}
			writes = append(writes, connectionSecrets(cur.ID, nil, p.Query, nil)...)
		}
		if p.HeadersSet {
			for _, h := range cur.CustomHeaders {
				if h.Secret {
					drop = append(drop, domain.SecretHeaderKey(cur.ID, h.Name))
				}
			}
			row.CustomHeaders = headerRow(p.Headers)
			writes = append(writes, connectionSecrets(cur.ID, p.Headers, nil, nil)...)
		}
		if p.URLVariablesSet {
			for _, v := range cur.URLVariables {
				drop = append(drop, domain.SecretURLVarKey(cur.ID, v))
			}
			row.URLVariables = varNames(p.URLVariables)
			writes = append(writes, connectionSecrets(cur.ID, nil, nil, p.URLVariables)...)
		}
		for _, name := range drop {
			if _, err := m.Delete(ctx, name); err != nil {
				return err
			}
		}
		if err := setSecrets(ctx, m, writes, &written); err != nil {
			return err
		}
		saved, err := s.d.OpenAPIWrites.Save(ctx, sess, id, row)
		if err != nil {
			return err
		}
		if !saved {
			return domain.ErrConnectionNotFound()
		}
		return nil
	})
	if err != nil {
		return ConnectionView{}, err
	}
	return s.GetConnection(ctx, c, id)
}

func parseUUIDPtr(s *string) *uuid.UUID {
	if s == nil {
		return nil
	}
	id, err := uuid.Parse(*s)
	if err != nil {
		return nil
	}
	return &id
}

// SpecPreview is preview_spec's answer.
type SpecPreview struct {
	Info  openapispec.Info
	Tools []openapispec.Tool
}

// maxPreviewChars is preview_spec's spec_content bound, json.dumps characters.
const maxPreviewChars = 5_000_000

// PreviewSpec is preview_spec: a spec read and parsed, nothing stored.
func (s *Service) PreviewSpec(ctx context.Context, specURL *string, specContent any) (SpecPreview, error) {
	spec := specContent
	if spec != nil {
		raw, err := wirejson.Marshal(spec, wirejson.Dumps)
		if err != nil {
			return SpecPreview{}, &domain.Invalid{Msg: err.Error()}
		}
		if len(raw) >= maxPreviewChars {
			return SpecPreview{}, &domain.Invalid{Msg: "spec_content exceeds 5MB limit."}
		}
	}
	if !openapispec.Truthy(spec) && specURL != nil {
		var err error
		if spec, err = s.fetchSpec(ctx, *specURL, nil); err != nil {
			return SpecPreview{}, err
		}
	}
	if !openapispec.Truthy(spec) {
		return SpecPreview{}, &domain.Invalid{Msg: "Provide spec_url or spec_content"}
	}
	tools, err := openapispec.ParseSpec(spec, nil)
	if err != nil {
		return SpecPreview{}, invalid(err)
	}
	info, err := openapispec.SpecInfo(spec)
	if err != nil {
		return SpecPreview{}, invalid(err)
	}
	return SpecPreview{Info: info, Tools: tools}, nil
}

// Discovery is discover_tools' answer.
type Discovery struct {
	ConnectionID string
	Tools        []openapispec.Tool
}

// DiscoverTools is discover_tools: the stored spec, else the one at its
// spec_url fetched with the connection's headers, parsed into its tools.
// A refused spec is *domain.Invalid; any other error is the route's 500.
func (s *Service) DiscoverTools(ctx context.Context, c authn.Caller, id uuid.UUID) (Discovery, error) {
	var conn domain.Connection
	err := s.read(ctx, c, func(sess db.Session) error {
		got, ok, err := s.d.OpenAPIWrites.Full(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.Invalid{Msg: fmt.Sprintf("Connection %s not found", id)}
		}
		conn = got
		return nil
	})
	if err != nil {
		return Discovery{}, err
	}
	spec := conn.SpecContent
	if !openapispec.Truthy(spec) {
		if conn.SpecURL == nil || *conn.SpecURL == "" {
			return Discovery{}, &domain.Invalid{Msg: fmt.Sprintf(
				"No spec_url or spec_content for connection %s. Provide a spec_url or upload spec_content.", conn.Name)}
		}
		headers, err := s.connectionHeaders(ctx, c.Workspace, c.UserID, conn)
		if err != nil {
			return Discovery{}, err
		}
		if spec, err = s.fetchSpec(ctx, *conn.SpecURL, headers); err != nil {
			return Discovery{}, err
		}
	}
	tools, err := openapispec.ParseSpec(spec, configuredQuery(conn.CustomQuery))
	if err != nil {
		return Discovery{}, invalid(err)
	}
	rawSpec, err := specJSON(spec)
	if err != nil {
		return Discovery{}, &domain.Invalid{Msg: err.Error()}
	}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		_, err := s.d.OpenAPIWrites.SetDiscovery(ctx, sess, id, toolsJSON(tools), rawSpec, s.d.Now())
		return err
	})
	if err != nil {
		return Discovery{}, err
	}
	return Discovery{ConnectionID: conn.ID, Tools: tools}, nil
}

// ConnectionToolPolicies is get_connection_tool_policies: each operation's
// workspace default beside the PDP's verdict on openapi:<id>:<tool>.
// governanceapi.ErrPolicyRefused when the workspace layer does not validate.
func (s *Service) ConnectionToolPolicies(ctx context.Context, c authn.Caller, id uuid.UUID) ([]ToolPolicy, error) {
	v, err := s.GetConnection(ctx, c, id)
	if err != nil {
		return nil, err
	}
	if s.d.Policies == nil {
		return nil, &domain.Unavailable{Msg: "tool policies are not available"}
	}
	rules, policy, err := s.d.Policies.Workspace(ctx, c)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	out := []ToolPolicy{}
	for _, t := range v.Connection.AvailableTools {
		if t.Name == "" || seen[t.Name] {
			continue
		}
		seen[t.Name] = true
		tool := openapispec.Slugify(t.Name)
		target := openapispec.ToolTarget(v.Connection.ID, tool)
		out = append(out, ToolPolicyOf(t.Name, "tool:"+target, target, []string{tool}, rules, policy))
	}
	return out, nil
}

// SetConnectionSharing is set_connection_sharing: the connection the
// workspace sees, shared with it or made its owner's again.
func (s *Service) SetConnectionSharing(ctx context.Context, c authn.Caller, id uuid.UUID, shared bool) (ConnectionView, error) {
	if _, err := s.GetConnection(ctx, c, id); err != nil {
		return ConnectionView{}, err
	}
	if err := s.SetSharing(ctx, c, id.String(), shared); err != nil {
		return ConnectionView{}, err
	}
	return s.GetConnection(ctx, c, id)
}
