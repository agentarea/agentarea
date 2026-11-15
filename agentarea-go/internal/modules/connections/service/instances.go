package service

import (
	"context"
	"errors"
	"sort"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// Outbox event types of an instance.
const (
	EventInstanceCreated = "com.agentarea.mcp.instance.created"
	EventInstanceUpdated = "MCPServerInstanceUpdated"
	EventInstanceDeleted = "com.agentarea.mcp.instance.deleted"
)

// ErrInstanceNotFound is the routes' 404.
func ErrInstanceNotFound() error { return &domain.NotFound{Msg: "MCP Server Instance not found"} }

var errNoRuntime = &domain.Unavailable{Msg: "the MCP runtime is not configured"}

// InstanceView is an instance as the routes show it: the bundle verification
// derived from its members, the names its response masks, and its sharing.
type InstanceView struct {
	Instance     domain.Instance
	Verification *domain.Verification
	SecretNames  map[string]bool
	Sharing      domain.Sharing
}

// GetInstance is the instance id the workspace sees (its own or a platform one).
func (s *Service) GetInstance(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.Instance, error) {
	var out domain.Instance
	err := s.read(ctx, c, func(sess db.Session) error {
		i, ok, err := s.d.Instances.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrInstanceNotFound()
		}
		out = i
		return nil
	})
	return out, err
}

// envSchema is the env_schema of the instance's spec; none when the spec is gone.
func (s *Service) envSchema(ctx context.Context, ws scope.Workspace, inst domain.Instance, cache map[string][]domain.EnvSchemaEntry) ([]domain.EnvSchemaEntry, error) {
	if s.d.Specs == nil || inst.ServerSpecID == "" {
		return nil, nil
	}
	if schema, ok := cache[inst.ServerSpecID]; ok {
		return schema, nil
	}
	spec, ok, err := s.d.Specs.Get(ctx, ws, inst.ServerSpecID, catalogapi.MCPSpecGet{PlatformBacked: inst.PlatformManaged()})
	if err != nil {
		return nil, err
	}
	var schema []domain.EnvSchemaEntry
	if ok {
		schema = domain.NormalizeEnvSchema(spec.EnvSchema)
	}
	if cache != nil {
		cache[inst.ServerSpecID] = schema
	}
	return schema, nil
}

// instanceViews renders rows; members are the bundles' member rows by their listed id.
func (s *Service) instanceViews(ctx context.Context, c authn.Caller, rows []domain.Instance, members map[string]domain.Instance) ([]InstanceView, error) {
	ids := make([]string, 0, len(rows))
	createdBy := map[string]string{}
	for _, r := range rows {
		ids = append(ids, r.ID)
		createdBy[r.ID] = r.CreatedBy
	}
	sharing, err := s.SharingOf(ctx, c, ids, createdBy)
	if err != nil {
		return nil, err
	}
	cache := map[string][]domain.EnvSchemaEntry{}
	out := make([]InstanceView, 0, len(rows))
	for _, r := range rows {
		schema, err := s.envSchema(ctx, c.Workspace, r, cache)
		if err != nil {
			return nil, err
		}
		v := InstanceView{Instance: r, SecretNames: domain.SecretNamesOf(schema, r.JSONSpec), Sharing: sharing[r.ID]}
		if r.Transport == domain.TransportBundle {
			d := domain.DeriveBundleVerification(r, members, s.d.Now())
			v.Verification = &d
		}
		out = append(out, v)
	}
	return out, nil
}

// bundleMembers reads every member a bundle among rows lists, keyed by the listed id.
func (s *Service) bundleMembers(ctx context.Context, sess db.Session, rows []domain.Instance) (map[string]domain.Instance, error) {
	var ids []uuid.UUID
	listed := map[string]string{}
	for _, r := range rows {
		if r.Transport != domain.TransportBundle {
			continue
		}
		for _, m := range domain.BundleMembers(r) {
			if id, err := uuid.Parse(m); err == nil {
				ids = append(ids, id)
				listed[id.String()] = m
			}
		}
	}
	if len(ids) == 0 {
		return nil, nil
	}
	found, err := s.d.Instances.GetMany(ctx, sess, ids)
	if err != nil {
		return nil, err
	}
	out := map[string]domain.Instance{}
	for id, i := range found {
		out[listed[id]] = i
	}
	return out, nil
}

// listInstances is service.list: the rows with a spec.
func (s *Service) listInstances(ctx context.Context, c authn.Caller) ([]domain.Instance, map[string]domain.Instance, error) {
	var rows []domain.Instance
	var members map[string]domain.Instance
	err := s.read(ctx, c, func(sess db.Session) error {
		all, err := s.d.Instances.List(ctx, sess)
		if err != nil {
			return err
		}
		for _, r := range all {
			if r.ServerSpecID != "" {
				rows = append(rows, r)
			}
		}
		members, err = s.bundleMembers(ctx, sess, rows)
		return err
	})
	return rows, members, err
}

// ListInstances is the instances the workspace sees, with a spec.
func (s *Service) ListInstances(ctx context.Context, c authn.Caller) ([]InstanceView, error) {
	rows, members, err := s.listInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	return s.instanceViews(ctx, c, rows, members)
}

// InstanceViewOf is the instance id as the detail route shows it; a row with
// no spec is 404 there.
func (s *Service) InstanceViewOf(ctx context.Context, c authn.Caller, id uuid.UUID, requireSpec bool) (InstanceView, error) {
	var inst domain.Instance
	var members map[string]domain.Instance
	err := s.read(ctx, c, func(sess db.Session) error {
		i, ok, err := s.d.Instances.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok || (requireSpec && i.ServerSpecID == "") {
			return ErrInstanceNotFound()
		}
		inst = i
		members, err = s.bundleMembers(ctx, sess, []domain.Instance{i})
		return err
	})
	if err != nil {
		return InstanceView{}, err
	}
	v, err := s.instanceViews(ctx, c, []domain.Instance{inst}, members)
	if err != nil {
		return InstanceView{}, err
	}
	return v[0], nil
}

// SetInstanceSharing is PUT /sharing: the instance must exist, then set_sharing.
func (s *Service) SetInstanceSharing(ctx context.Context, c authn.Caller, id uuid.UUID, shared bool) (InstanceView, error) {
	if _, err := s.GetInstance(ctx, c, id); err != nil {
		return InstanceView{}, err
	}
	if err := s.SetSharing(ctx, c, id.String(), shared); err != nil {
		return InstanceView{}, err
	}
	return s.InstanceViewOf(ctx, c, id, false)
}

// endpointRefusal is _endpoint_refusal: a member-supplied endpoint the
// outbound policy refuses; a name that does not resolve yet passes.
func (s *Service) endpointRefusal(ctx context.Context, raw any) (string, error) {
	u, _ := raw.(string)
	if u == "" {
		return "", nil
	}
	if s.d.Out == nil {
		return "", &domain.Unavailable{Msg: "outbound HTTP is not configured"}
	}
	_, err := s.d.Out.Guard().CheckURL(ctx, u)
	var re *netguard.ResolveError
	switch {
	case err == nil, errors.As(err, &re):
		return "", nil
	case errors.Is(err, netguard.ErrUnsafe):
		s.d.Log.WarnContext(ctx, "refused MCP endpoint", "url", u, "error", err)
		return "Endpoint URL is not an allowed address", nil
	}
	return "", err
}

// secretRefs is assert_may_use_secret_refs as the references to stage: every
// named secret must be a workspace secret the caller may use.
func (s *Service) secretRefs(ctx context.Context, c authn.Caller, refs map[string]string) ([]ksecrets.Reference, error) {
	if len(refs) == 0 {
		return nil, nil
	}
	fields := make([]string, 0, len(refs))
	for f := range refs {
		fields = append(fields, f)
	}
	sort.Strings(fields)
	catalog := s.d.Catalog(c.Workspace, actor(c))
	ids := map[string]string{}
	out := make([]ksecrets.Reference, 0, len(refs))
	for _, f := range fields {
		name := refs[f]
		id, ok := ids[name]
		if !ok {
			sec, err := catalog.GetNamedForUse(ctx, name)
			switch {
			case errors.Is(err, ksecrets.ErrNotFound):
				return nil, domain.Refused("Secret '" + name + "' is not a secret of this workspace")
			case errors.Is(err, ksecrets.ErrManaged):
				return nil, domain.Refused("Secret '" + name + "' belongs to a connection; reference a workspace secret instead")
			case errors.Is(err, ksecrets.ErrAccessDenied):
				return nil, &domain.Forbidden{Msg: err.Error()}
			case err != nil:
				return nil, err
			}
			id = sec.ID
			ids[name] = id
		}
		out = append(out, ksecrets.Reference{SecretID: id, Field: f})
	}
	return out, nil
}

func hasSecretRefs(spec map[string]any) bool {
	for _, field := range []string{"environment", "headers"} {
		if values, ok := spec[field].(map[string]any); ok {
			for _, v := range values {
				if domain.IsSecretRef(v) {
					return true
				}
			}
		}
	}
	return false
}

func (s *Service) retire(ctx context.Context, id string) error {
	if s.d.Runtime == nil {
		return errNoRuntime
	}
	return s.d.Runtime.Retire(ctx, id)
}

func (s *Service) instanceGraphWriter() (authz.Writer, error) {
	w, ok := s.d.Graph.(authz.Writer)
	if !ok {
		return nil, errNoGraphWriter
	}
	return w, nil
}

func stringOf(v any) *string {
	if s, ok := v.(string); ok {
		return &s
	}
	return nil
}

// globLiteral is a name as an fnmatch pattern matching only itself.
func globLiteral(name string) string {
	var b strings.Builder
	for _, r := range name {
		if r == '*' || r == '?' || r == '[' {
			b.WriteString("[" + string(r) + "]")
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

// InstancePorts says which instance routes have their ports.
type InstancePorts struct {
	Specs, Runtime, Consumers, Policies bool
}

// InstancePorts reports the instance routes' ports.
func (s *Service) InstancePorts() InstancePorts {
	return InstancePorts{Specs: s.d.Specs != nil, Runtime: s.d.Runtime != nil,
		Consumers: s.d.Agents != nil && s.d.Approvals != nil, Policies: s.d.Policies != nil}
}
