package service

import (
	"context"
	"errors"
	"reflect"
	"sort"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

const specReferenceRefusal = "A server spec may not reference a workspace secret; an instance references it"

// ErrSpecNotFound is the routes' 404 for a spec.
func ErrSpecNotFound() error { return &domain.NotFound{Msg: "MCP Server not found"} }

// SpecPatch is MCPServerUpdate: Set names the fields the body carried.
type SpecPatch struct {
	Set                                    map[string]bool
	Name, Description, Version, Status     string
	DockerImageURL, RemoteURL, RegistryURL *string
	IsPublic                               bool
	Tags, EnvSchema, Cmd                   []any
	JSONSpec                               map[string]any
}

// specTransportColumns is SPEC_TRANSPORT_COLUMNS.
func specTransportColumns() []string {
	return []string{"json_spec", "remote_url", "cmd", "docker_image_url"}
}

// ListSpecs is GET /mcp-servers/: the workspace's specs the graph lets c
// read, then the catalog.
func (s *Service) ListSpecs(ctx context.Context, c authn.Caller, q catalogapi.MCPSpecQuery) ([]catalogapi.MCPSpec, int, error) {
	specs, err := s.specs()
	if err != nil {
		return nil, 0, err
	}
	readable, err := s.ReadableIDs(ctx, c)
	if err != nil {
		return nil, 0, err
	}
	q.Readable = make([]string, 0, len(readable))
	for id := range readable {
		q.Readable = append(q.Readable, id)
	}
	sort.Strings(q.Readable)
	return specs.List(ctx, c.Workspace, q)
}

// ResolveSpecID is _resolve_server_id: a UUID as given, else the
// workspace's spec with that slug.
func (s *Service) ResolveSpecID(ctx context.Context, c authn.Caller, ident string) (string, error) {
	if u, err := uuid.Parse(ident); err == nil {
		return u.String(), nil
	}
	specs, err := s.specs()
	if err != nil {
		return "", err
	}
	sp, ok, err := specs.BySlug(ctx, c.Workspace, ident)
	if err != nil {
		return "", err
	}
	if !ok {
		return "", ErrSpecNotFound()
	}
	return sp.ID, nil
}

// GetSpec is GET /mcp-servers/{server_id}: a tenant spec needs read on it,
// catalog data does not.
func (s *Service) GetSpec(ctx context.Context, c authn.Caller, ident string) (catalogapi.MCPSpec, error) {
	id, err := s.ResolveSpecID(ctx, c, ident)
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	sp, ok, err := s.MCPSpec(ctx, c, id)
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	if !ok {
		return catalogapi.MCPSpec{}, ErrSpecNotFound()
	}
	if !sp.Catalog {
		if err := s.Require(ctx, c, "read", "mcp_server", id); err != nil {
			return catalogapi.MCPSpec{}, err
		}
	}
	return sp, nil
}

// specEndpointRefusal is _spec_endpoint_refusal.
func (s *Service) specEndpointRefusal(ctx context.Context, remoteURL *string, jsonSpec map[string]any) error {
	if remoteURL != nil {
		refusal, err := s.endpointRefusal(ctx, *remoteURL)
		if err != nil || refusal != "" {
			return refusalOrErr(refusal, err)
		}
	}
	spec := domain.NormalizeURLKeys(jsonSpec)
	if spec["type"] == domain.TransportURL {
		refusal, err := s.endpointRefusal(ctx, spec["endpoint_url"])
		return refusalOrErr(refusal, err)
	}
	return nil
}

func refusalOrErr(refusal string, err error) error {
	if err != nil {
		return err
	}
	if refusal != "" {
		return domain.Refused(refusal)
	}
	return nil
}

// serverEgressRefusal is _server_egress_refusal in an edition without exits.
func serverEgressRefusal(sp catalogapi.MCPSpec) error {
	spec := sp.JSONSpec
	if !domain.EgressRequired(spec) {
		return nil
	}
	t, _ := domain.ServerTransportSpec(spec, sp.RemoteURL, sp.Cmd, sp.DockerImageURL)["type"].(string)
	if !domain.IsContainer(t) {
		return domain.Refused(domain.EgressSpecKey + " applies to docker and command servers only")
	}
	return domain.Refused(domain.EgressExitsUnsupported)
}

// CreateSpec is create_mcp_server, then the route's owner grant.
func (s *Service) CreateSpec(ctx context.Context, c authn.Caller, n catalogapi.MCPSpecNew) (catalogapi.MCPSpec, error) {
	specs, err := s.specs()
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	if err := s.specEndpointRefusal(ctx, n.RemoteURL, n.JSONSpec); err != nil {
		return catalogapi.MCPSpec{}, err
	}
	if domain.CarriesSecretRef(n.JSONSpec) {
		return catalogapi.MCPSpec{}, domain.Refused(specReferenceRefusal)
	}
	if err := serverEgressRefusal(catalogapi.MCPSpec{JSONSpec: n.JSONSpec, RemoteURL: n.RemoteURL, Cmd: n.Cmd,
		DockerImageURL: n.DockerImageURL}); err != nil {
		return catalogapi.MCPSpec{}, err
	}
	var sp catalogapi.MCPSpec
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		if sp, err = specs.Create(ctx, tx, c.UserID, n); err != nil {
			return err
		}
		return s.auditSpec(ctx, tx, c, "mcp_server.create", sp.ID)
	})
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	w, err := s.instanceGraphWriter()
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	if err := authz.GrantResourceOwner(ctx, w, sp.ID, c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
		return catalogapi.MCPSpec{}, err
	}
	return sp, nil
}

// UpdateSpec is PATCH /mcp-servers/{server_id}: edit on the spec, then
// update_mcp_server on the workspace's row.
func (s *Service) UpdateSpec(ctx context.Context, c authn.Caller, ident string, p SpecPatch) (catalogapi.MCPSpec, error) {
	id, cur, err := s.editableSpec(ctx, c, ident)
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	if p.Set["remote_url"] || p.Set["json_spec"] {
		if err := s.specEndpointRefusal(ctx, p.RemoteURL, p.JSONSpec); err != nil {
			return catalogapi.MCPSpec{}, err
		}
	}
	if domain.CarriesSecretRef(p.JSONSpec) {
		return catalogapi.MCPSpec{}, domain.Refused(specReferenceRefusal)
	}
	next := p.apply(cur)
	touched, redirected := false, false
	for _, col := range specTransportColumns() {
		if p.Set[col] {
			touched = true
			redirected = redirected || !reflect.DeepEqual(transportColumn(next, col), transportColumn(cur, col))
		}
	}
	if touched {
		if err := serverEgressRefusal(next); err != nil {
			return catalogapi.MCPSpec{}, err
		}
	}
	if redirected {
		if err := s.assertMayRedirectSecretRefs(ctx, c, id); err != nil {
			return catalogapi.MCPSpec{}, err
		}
	}
	specs, _ := s.specs()
	var out catalogapi.MCPSpec
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		var ok bool
		if out, ok, err = specs.Update(ctx, tx, next, c.UserID); err != nil {
			return err
		}
		if !ok {
			return ErrSpecNotFound()
		}
		return s.auditSpec(ctx, tx, c, "mcp_server.update", id)
	})
	return out, err
}

func transportColumn(sp catalogapi.MCPSpec, col string) any {
	switch col {
	case "json_spec":
		return sp.JSONSpec
	case "remote_url":
		return sp.RemoteURL
	case "cmd":
		return sp.Cmd
	}
	return sp.DockerImageURL
}

func (p SpecPatch) apply(sp catalogapi.MCPSpec) catalogapi.MCPSpec {
	if p.Set["name"] {
		sp.Name = p.Name
	}
	if p.Set["description"] {
		sp.Description = p.Description
	}
	if p.Set["docker_image_url"] {
		sp.DockerImageURL = p.DockerImageURL
	}
	if p.Set["remote_url"] {
		sp.RemoteURL = p.RemoteURL
	}
	if p.Set["version"] {
		sp.Version = p.Version
	}
	if p.Set["tags"] {
		sp.Tags = p.Tags
	}
	if p.Set["is_public"] {
		sp.IsPublic = p.IsPublic
	}
	if p.Set["status"] {
		sp.Status = p.Status
	}
	if p.Set["env_schema"] {
		sp.EnvSchema = p.EnvSchema
	}
	if p.Set["cmd"] {
		sp.Cmd = p.Cmd
	}
	if p.Set["json_spec"] {
		sp.JSONSpec = p.JSONSpec
	}
	if p.Set["registry_url"] {
		sp.RegistryURL = p.RegistryURL
	}
	return sp
}

// assertMayRedirectSecretRefs is _assert_may_redirect_secret_refs: moving
// where a spec's instances connect sends their referenced secrets there, so
// it takes use of every workspace secret they reference.
func (s *Service) assertMayRedirectSecretRefs(ctx context.Context, c authn.Caller, specID string) error {
	var insts []domain.Instance
	err := s.read(ctx, c, func(sess db.Session) error {
		all, err := s.d.Instances.List(ctx, sess)
		for _, inst := range all {
			if inst.ServerSpecID == specID && inst.WorkspaceID == c.Workspace.ID() {
				insts = append(insts, inst)
			}
		}
		return err
	})
	if err != nil {
		return err
	}
	names := map[string]bool{}
	for _, inst := range insts {
		refs, err := domain.SpecSecretRefs(inst.JSONSpec)
		if err != nil {
			continue
		}
		for _, name := range refs {
			names[name] = true
		}
	}
	sorted := make([]string, 0, len(names))
	for n := range names {
		sorted = append(sorted, n)
	}
	sort.Strings(sorted)
	catalog := s.d.Catalog(c.Workspace, actor(c))
	for _, name := range sorted {
		_, err := catalog.GetNamedForUse(ctx, name)
		switch {
		case errors.Is(err, ksecrets.ErrNotFound), errors.Is(err, ksecrets.ErrManaged):
			s.d.Log.InfoContext(ctx, "Spec transport change: instance reference resolves to nothing", "spec_id", specID, "secret", name)
		case errors.Is(err, ksecrets.ErrAccessDenied):
			return &domain.Forbidden{Msg: err.Error()}
		case err != nil:
			return err
		}
	}
	return nil
}

// editableSpec resolves ident, takes edit on it and reads the workspace's row.
func (s *Service) editableSpec(ctx context.Context, c authn.Caller, ident string) (string, catalogapi.MCPSpec, error) {
	return s.ownSpec(ctx, c, ident, "edit")
}

func (s *Service) ownSpec(ctx context.Context, c authn.Caller, ident, permission string) (string, catalogapi.MCPSpec, error) {
	id, err := s.ResolveSpecID(ctx, c, ident)
	if err != nil {
		return "", catalogapi.MCPSpec{}, err
	}
	if err := s.Require(ctx, c, permission, "mcp_server", id); err != nil {
		return "", catalogapi.MCPSpec{}, err
	}
	sp, ok, err := s.MCPSpec(ctx, c, id)
	if err != nil {
		return "", catalogapi.MCPSpec{}, err
	}
	if !ok || sp.WorkspaceID != c.Workspace.ID() {
		return "", catalogapi.MCPSpec{}, ErrSpecNotFound()
	}
	return id, sp, nil
}

// DeleteSpec is DELETE /mcp-servers/{server_id}.
func (s *Service) DeleteSpec(ctx context.Context, c authn.Caller, ident string) error {
	id, err := s.ResolveSpecID(ctx, c, ident)
	if err != nil {
		return err
	}
	if err := s.Require(ctx, c, "delete", "mcp_server", id); err != nil {
		return err
	}
	specs, err := s.specs()
	if err != nil {
		return err
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		ok, err := specs.Delete(ctx, tx, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrSpecNotFound()
		}
		return s.auditSpec(ctx, tx, c, "mcp_server.delete", id)
	})
}

// DeploySpec is POST /mcp-servers/{server_id}/deploy: the spec's status
// becomes deployed.
func (s *Service) DeploySpec(ctx context.Context, c authn.Caller, ident string) (catalogapi.MCPSpec, error) {
	_, cur, err := s.editableSpec(ctx, c, ident)
	if err != nil {
		return catalogapi.MCPSpec{}, err
	}
	cur.Status = "deployed"
	specs, _ := s.specs()
	var out catalogapi.MCPSpec
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		var ok bool
		if out, ok, err = specs.Update(ctx, tx, cur, c.UserID); err != nil {
			return err
		}
		if !ok {
			return ErrSpecNotFound()
		}
		return nil
	})
	return out, err
}

// auditSpec is @audited on the spec writes, in their transaction.
func (s *Service) auditSpec(ctx context.Context, tx db.Session, c authn.Caller, action, id string) error {
	if s.d.Audit == nil {
		return errors.New("connections: " + action + " cannot be audited: no audit writer")
	}
	return s.d.Audit.RecordOnce(ctx, tx, governanceapi.AuditRecord{
		EventID: s.d.NewID().String(), Action: action, ResourceType: "mcp_server", ResourceID: id,
		ActorType: "user", ActorID: c.UserID,
	})
}
