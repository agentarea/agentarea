package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"sort"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// InstanceCreate is MCPServerInstanceCreate, validated. An empty
// ServerSpecID makes the instance its own spec from JSONSpec.
type InstanceCreate struct {
	Name          string
	Description   *string
	ServerSpecID  string
	JSONSpec      map[string]any
	AuthConfigID  *string
	ContextSecret *string
}

// InstancePatchIn is MCPServerInstanceUpdate: only the fields set change.
type InstancePatchIn struct {
	Name             *string
	Description      *string
	DescriptionSet   bool
	JSONSpec         map[string]any
	ContextSecret    *string
	ContextSecretSet bool
	Cost             map[string]any
	CostSet          bool
}

// autoSpec is _auto_create_spec_for_instance: the spec an instance created
// without one declares from its own transport keys.
func autoSpec(in InstanceCreate) (catalogapi.MCPSpecNew, error) {
	spec := domain.NormalizeURLKeys(in.JSONSpec)
	t, _ := spec["type"].(string)
	if t != domain.TransportURL && t != domain.TransportDocker && t != domain.TransportCommand {
		return catalogapi.MCPSpecNew{}, domain.Refused("json_spec.type must be one of: url, docker, command")
	}
	transport := map[string]any{}
	for _, k := range domain.InstanceTransportFields() {
		if v, ok := spec[k]; ok {
			transport[k] = v
		}
	}
	var schema []any
	for _, f := range []struct{ key, desc string }{{"headers", "HTTP header "}, {"environment", "Environment variable "}} {
		if m, ok := spec[f.key].(map[string]any); ok {
			for _, name := range sortedNames(m) {
				schema = append(schema, map[string]any{"name": name, "description": f.desc + name, "isSecret": true})
			}
		}
	}
	desc := in.Name
	if in.Description != nil && *in.Description != "" {
		desc = *in.Description
	}
	n := catalogapi.MCPSpecNew{Name: in.Name, Description: desc, Version: "1.0.0", Tags: []any{},
		EnvSchema: schema, JSONSpec: transport}
	switch t {
	case domain.TransportDocker:
		n.DockerImageURL = stringOf(transport["image"])
	case domain.TransportURL:
		n.RemoteURL = stringOf(transport["endpoint_url"])
	case domain.TransportCommand:
		if domain.Truthy(transport["command"]) {
			args, _ := transport["args"].([]any)
			n.Cmd = append([]any{transport["command"]}, args...)
		}
	}
	return n, nil
}

func sortedNames(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// createPlan is what the checks before the insert settled.
type createPlan struct {
	spec      catalogapi.MCPSpec
	transport string
	stored    map[string]any
	secrets   map[string]string
	refs      []ksecrets.Reference
}

// checkSpec runs create_instance's refusals in Python's order.
func (s *Service) checkSpec(ctx context.Context, c authn.Caller, spec catalogapi.MCPSpec, in InstanceCreate, submitted map[string]any) (createPlan, error) {
	if domain.CarriesSecretRef(spec.JSONSpec) {
		return createPlan{}, domain.Refused("MCP server spec '" + spec.Name + "' carries a secret reference; only an instance may reference a workspace secret")
	}
	transportSpec := domain.ServerTransportSpec(spec.JSONSpec, spec.RemoteURL, spec.Cmd, spec.DockerImageURL)
	if errs := domain.ValidateJSONSpec(transportSpec); len(errs) > 0 {
		return createPlan{}, &domain.SpecInvalid{Errors: errs}
	}
	t, _ := transportSpec["type"].(string)
	if t == "" {
		return createPlan{}, domain.Refused("MCP server " + spec.ID + " declares no transport")
	}
	if t == domain.TransportURL {
		refusal, err := s.endpointRefusal(ctx, transportSpec["endpoint_url"])
		if err != nil {
			return createPlan{}, err
		}
		if refusal != "" {
			return createPlan{}, domain.Refused(refusal)
		}
	}
	if in.ContextSecret != nil && *in.ContextSecret != "" && t != domain.TransportURL {
		return createPlan{}, domain.Refused("context_secret applies to URL instances only")
	}
	if err := s.egressExitRefusal(ctx, c, submitted, t); err != nil {
		return createPlan{}, err
	}
	own := map[string]any{}
	for k, v := range submitted {
		if !contains(domain.InstanceTransportFields(), k) && k != domain.ContextSigningFlag {
			own[k] = v
		}
	}
	merged := domain.MergeTransportSpec(transportSpec, own, t)
	if err := s.egressRequirementRefusal(merged, t); err != nil {
		return createPlan{}, err
	}
	if t == domain.TransportDocker && domain.ImageServesStdio(merged) {
		return createPlan{}, domain.Refused(fmt.Sprintf("Image '%v' speaks stdio; an image runs only when it serves MCP "+
			"over HTTP on a port, so use the server's npm or PyPI package instead", merged["image"]))
	}
	if e := domain.ToolTimeoutError(own); e != "" {
		return createPlan{}, domain.Refused(e)
	}
	stored, secrets, err := domain.ExtractSecrets(own, domain.NormalizeEnvSchema(spec.EnvSchema), nil)
	if err != nil {
		return createPlan{}, err
	}
	names, err := domain.SpecSecretRefs(stored)
	if err != nil {
		return createPlan{}, domain.Refused(err.Error())
	}
	refs, err := s.secretRefs(ctx, c, names)
	if err != nil {
		return createPlan{}, err
	}
	if in.ContextSecret != nil && *in.ContextSecret != "" {
		stored[domain.ContextSigningFlag] = true
	}
	return createPlan{spec: spec, transport: t, stored: stored, secrets: secrets, refs: refs}, nil
}

// egressExitRefusal is _assert_may_bind_egress_exit: an instance leaves
// through an exit of its workspace, or the platform's.
func (s *Service) egressExitRefusal(ctx context.Context, c authn.Caller, spec map[string]any, transport string) error {
	if spec[domain.EgressExitSpecKey] == nil {
		return nil
	}
	if !domain.IsContainer(transport) {
		return domain.Refused(domain.EgressExitSpecKey + " applies to docker and command instances only")
	}
	if s.d.EgressExits == nil {
		return domain.Refused(domain.EgressExitsUnsupported)
	}
	exitID, _ := spec[domain.EgressExitSpecKey].(string)
	err := s.d.EgressExits.RequireBindable(ctx, c, exitID)
	var nf *governanceapi.EgressExitNotFoundError
	if errors.As(err, &nf) {
		return domain.Refused(nf.Error())
	}
	return err
}

// egressRequirementRefusal is _egress_requirement_refusal: a workload that
// must leave through an exit runs only where one is sealed for it.
func (s *Service) egressRequirementRefusal(spec map[string]any, transport string) error {
	if !domain.EgressRequired(spec) {
		return nil
	}
	if !domain.IsContainer(transport) {
		return domain.Refused(domain.EgressSpecKey + " applies to docker and command servers only")
	}
	if s.d.EgressExits == nil {
		return domain.Refused(domain.EgressExitsUnsupported)
	}
	return nil
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// CreateInstance is create_instance.
func (s *Service) CreateInstance(ctx context.Context, c authn.Caller, in InstanceCreate) (InstanceView, error) {
	return s.createInstance(ctx, c, in, nil)
}

// CreateInstanceWithSpec is create_instance_with_spec: the spec and its
// instance in one transaction.
func (s *Service) CreateInstanceWithSpec(ctx context.Context, c authn.Caller, server catalogapi.MCPSpecNew, in InstanceCreate) (InstanceView, error) {
	if domain.CarriesSecretRef(server.JSONSpec) {
		return InstanceView{}, domain.Refused("A server spec may not reference a workspace secret; an instance references it")
	}
	return s.createInstance(ctx, c, in, &server)
}

func (s *Service) createInstance(ctx context.Context, c authn.Caller, in InstanceCreate, server *catalogapi.MCPSpecNew) (InstanceView, error) {
	submitted := domain.NormalizeURLKeys(in.JSONSpec)
	var spec catalogapi.MCPSpec
	copyFrom := (*catalogapi.MCPSpec)(nil)
	if server == nil && in.ServerSpecID != "" {
		got, ok, err := s.d.Specs.Get(ctx, c.Workspace, in.ServerSpecID, catalogapi.MCPSpecGet{})
		if err != nil {
			return InstanceView{}, err
		}
		if !ok {
			return InstanceView{}, domain.Refused("server_spec_id '" + in.ServerSpecID + "' was not found")
		}
		if got.WorkspaceID != c.Workspace.ID() {
			copyFrom = &got
		}
		spec = got
	}
	if server == nil && in.ServerSpecID == "" {
		n, err := autoSpec(in)
		if err != nil {
			return InstanceView{}, err
		}
		server = &n
	}
	var authID *uuid.UUID
	if in.AuthConfigID != nil && *in.AuthConfigID != "" {
		id, err := uuid.Parse(*in.AuthConfigID)
		if err != nil {
			return InstanceView{}, &domain.Invalid{Msg: "Auth config " + *in.AuthConfigID + " not found in this workspace"}
		}
		authID = &id
	}
	id := s.d.NewID()
	createdSpec := ""
	var plan createPlan
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		var err error
		switch {
		case server != nil:
			if spec, err = s.d.Specs.Create(ctx, tx, c.UserID, *server); err != nil {
				return err
			}
			createdSpec = spec.ID
		case copyFrom != nil:
			if spec, err = s.d.Specs.MaterializeCopy(ctx, tx, c.UserID, *copyFrom); err != nil {
				return err
			}
			createdSpec = spec.ID
		}
		if plan, err = s.checkSpec(ctx, c, spec, in, submitted); err != nil {
			return err
		}
		if authID != nil {
			if _, err := s.GetAuthConfigForUse(ctx, tx, c, *authID); err != nil {
				return err
			}
		}
		inst, err := s.d.Instances.Insert(ctx, tx, store.InstanceNew{ID: id, CreatedBy: c.UserID, Name: in.Name,
			Description: in.Description, ServerSpecID: spec.ID, Transport: plan.transport, JSONSpec: plan.stored,
			AuthConfigID: authID, Now: s.d.Now()})
		if err != nil {
			return err
		}
		if len(plan.refs) > 0 {
			if err := s.d.Catalog(c.Workspace, actor(c)).StageReferences(ctx, tx, domain.SecretRefConsumer, inst.ID, plan.refs); err != nil {
				return err
			}
		}
		m := s.d.Secrets.Manager(tx, c.UserID)
		for _, name := range sortedSecretNames(plan.secrets) {
			if err := m.Set(ctx, domain.InstanceSecretName(inst.ID, name), plan.secrets[name]); err != nil {
				return err
			}
		}
		if in.ContextSecret != nil && *in.ContextSecret != "" {
			if err := m.Set(ctx, domain.InstanceSecretName(inst.ID, domain.ContextSecretName), *in.ContextSecret); err != nil {
				return err
			}
		}
		if err := s.auditWrite(ctx, tx, c, "mcp_instance.create", "mcp_instance", inst.ID); err != nil {
			return err
		}
		return events.Publish(ctx, tx, c.UserID, events.NewEnvelope(EventInstanceCreated, map[string]any{
			"instance_id": inst.ID, "server_spec_id": spec.ID, "name": inst.Name, "json_spec": plan.stored,
		}))
	})
	if err != nil {
		return InstanceView{}, err
	}
	if err := s.grantOwner(ctx, c, createdSpec, id.String()); err != nil {
		return InstanceView{}, err
	}
	if plan.transport == domain.TransportURL {
		if _, err := s.Verify(ctx, c.Workspace, id, false); err != nil {
			s.d.Log.ErrorContext(ctx, "verification of a new MCP instance failed", "instance_id", id.String(), "error", err)
		}
	} else {
		s.VerifyInBackground(c.Workspace, id)
	}
	return s.InstanceViewOf(ctx, c, id, false)
}

// grantOwner is _grant_creator_ownership of the spec created with the
// instance, then of the instance, which starts personal.
func (s *Service) grantOwner(ctx context.Context, c authn.Caller, specID, instanceID string) error {
	w, err := s.instanceGraphWriter()
	if err != nil {
		return err
	}
	if specID != "" {
		if err := authz.GrantResourceOwner(ctx, w, specID, c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
			return err
		}
	}
	if err := authz.GrantResourceOwner(ctx, w, instanceID, c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
		return err
	}
	return authz.MakePersonal(ctx, w, instanceID)
}

func sortedSecretNames(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func withoutKey(m map[string]any, key string) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		if k != key {
			out[k] = v
		}
	}
	return out
}

// sameJSON compares two decoded specs as JSON, numbers by their text.
func sameJSON(a, b map[string]any) bool {
	ra, errA := json.Marshal(a)
	rb, errB := json.Marshal(b)
	if errA != nil || errB != nil {
		return reflect.DeepEqual(a, b)
	}
	var x, y any
	if json.Unmarshal(ra, &x) != nil || json.Unmarshal(rb, &y) != nil {
		return string(ra) == string(rb)
	}
	return reflect.DeepEqual(x, y)
}

// specUpdate is what a json_spec patch settled before any write.
type specUpdate struct {
	stored   map[string]any
	secrets  map[string]string
	refs     []ksecrets.Reference
	record   bool
	replaced []string
}

func (s *Service) planSpecUpdate(ctx context.Context, c authn.Caller, inst domain.Instance, patch map[string]any) (specUpdate, bool, error) {
	spec := withoutKey(domain.NormalizeURLKeys(patch), domain.ContextSigningFlag)
	if e := domain.ToolTimeoutError(spec); e != "" {
		return specUpdate{}, false, domain.Refused(e)
	}
	if !reflect.DeepEqual(spec[domain.EgressExitSpecKey], inst.JSONSpec[domain.EgressExitSpecKey]) {
		if err := s.egressExitRefusal(ctx, c, spec, inst.Transport); err != nil {
			return specUpdate{}, false, err
		}
	}
	schema, err := s.envSchema(ctx, c.Workspace, inst, nil)
	if err != nil {
		return specUpdate{}, false, err
	}
	stored, secrets, err := domain.ExtractSecrets(spec, schema, inst.JSONSpec)
	if err != nil {
		return specUpdate{}, false, err
	}
	names, err := domain.SpecSecretRefs(stored)
	if err != nil {
		return specUpdate{}, false, domain.Refused(err.Error())
	}
	refs, err := s.secretRefs(ctx, c, names)
	if err != nil {
		return specUpdate{}, false, err
	}
	u := specUpdate{stored: stored, secrets: secrets, refs: refs, record: len(names) > 0 || hasSecretRefs(inst.JSONSpec)}
	for _, n := range inst.EnvVars() {
		if _, ok := names[n]; ok {
			u.replaced = append(u.replaced, n)
		}
	}
	if domain.Truthy(inst.JSONSpec[domain.ContextSigningFlag]) {
		stored[domain.ContextSigningFlag] = true
	}
	for _, f := range domain.InstanceSystemFields() {
		if v, ok := inst.JSONSpec[f]; ok {
			if _, set := stored[f]; !set {
				stored[f] = v
			}
		}
	}
	changed := !sameJSON(withoutKey(stored, domain.ToolTimeoutKey), withoutKey(inst.JSONSpec, domain.ToolTimeoutKey)) || len(secrets) > 0
	return u, changed, nil
}

// UpdateInstance is update_instance. A container instance whose runtime
// configuration changes is retired before anything is written, so a failed
// retirement leaves the stored state as the running one.
func (s *Service) UpdateInstance(ctx context.Context, c authn.Caller, id uuid.UUID, p InstancePatchIn) (InstanceView, error) {
	inst, err := s.GetInstance(ctx, c, id)
	if err != nil {
		return InstanceView{}, err
	}
	if p.CostSet && inst.PlatformManaged() {
		return InstanceView{}, domain.Refused("the cost of a platform connection is not set on it")
	}
	if inst.PlatformManaged() || inst.WorkspaceID != c.Workspace.ID() {
		return InstanceView{}, ErrInstanceNotFound()
	}
	var upd *specUpdate
	if p.JSONSpec != nil {
		u, changed, err := s.planSpecUpdate(ctx, c, inst, p.JSONSpec)
		if err != nil {
			return InstanceView{}, err
		}
		if changed && domain.IsContainer(inst.Transport) {
			if err := s.retire(ctx, inst.ID); err != nil {
				return InstanceView{}, err
			}
		}
		upd = &u
	}
	if p.ContextSecretSet && p.ContextSecret != nil && *p.ContextSecret != "" && inst.Transport != domain.TransportURL {
		return InstanceView{}, domain.Refused("context_secret applies to URL instances only")
	}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		cur, ok, err := s.d.Instances.Lock(ctx, tx, id)
		if err != nil {
			return err
		}
		if !ok || cur.WorkspaceID != c.Workspace.ID() {
			return ErrInstanceNotFound()
		}
		m := s.d.Secrets.Manager(tx, c.UserID)
		spec := cur.JSONSpec
		if upd != nil {
			for _, n := range upd.replaced {
				if _, err := m.Delete(ctx, domain.InstanceSecretName(cur.ID, n)); err != nil {
					return err
				}
			}
			for _, n := range sortedSecretNames(upd.secrets) {
				if err := m.Set(ctx, domain.InstanceSecretName(cur.ID, n), upd.secrets[n]); err != nil {
					return err
				}
			}
			spec = upd.stored
		}
		if p.ContextSecretSet {
			spec = withoutKey(spec, domain.ContextSigningFlag)
			name := domain.InstanceSecretName(cur.ID, domain.ContextSecretName)
			if p.ContextSecret != nil && *p.ContextSecret != "" {
				if err := m.Set(ctx, name, *p.ContextSecret); err != nil {
					return err
				}
				spec[domain.ContextSigningFlag] = true
			} else if _, err := m.Delete(ctx, name); err != nil {
				return err
			}
		}
		if upd != nil && upd.record {
			if err := s.d.Catalog(c.Workspace, actor(c)).StageReferences(ctx, tx, domain.SecretRefConsumer, cur.ID, upd.refs); err != nil {
				return err
			}
		}
		patch := store.InstancePatch{Name: cur.Name, Description: cur.Description, JSONSpec: spec, Cost: cur.Cost, Now: s.d.Now()}
		if p.Name != nil {
			patch.Name = *p.Name
		}
		if p.DescriptionSet {
			patch.Description = p.Description
		}
		if p.CostSet {
			patch.Cost = p.Cost
		}
		if ok, err := s.d.Instances.Update(ctx, tx, id, patch); err != nil {
			return err
		} else if !ok {
			return ErrInstanceNotFound()
		}
		if err := s.auditWrite(ctx, tx, c, "mcp_instance.update", "mcp_instance", cur.ID); err != nil {
			return err
		}
		return events.Publish(ctx, tx, c.UserID, events.NewEnvelope(EventInstanceUpdated, map[string]any{
			"instance_id": cur.ID, "server_spec_id": cur.ServerSpecID, "name": patch.Name, "status": cur.Verification.Status,
		}))
	})
	if err != nil {
		return InstanceView{}, err
	}
	return s.InstanceViewOf(ctx, c, id, false)
}

// DeleteInstance is delete_instance: the runtime is retired first, then the
// instance's secrets, the auth configs minted for it and its references go
// with its row.
func (s *Service) DeleteInstance(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	inst, err := s.GetInstance(ctx, c, id)
	if err != nil {
		return err
	}
	if inst.PlatformManaged() || inst.WorkspaceID != c.Workspace.ID() {
		return ErrInstanceNotFound()
	}
	if domain.IsContainer(inst.Transport) {
		if err := s.retire(ctx, inst.ID); err != nil {
			return err
		}
	}
	var owned []domain.AuthConfig
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		cur, ok, err := s.d.Instances.Lock(ctx, tx, id)
		if err != nil {
			return err
		}
		if !ok || cur.WorkspaceID != c.Workspace.ID() {
			return ErrInstanceNotFound()
		}
		m := s.d.Secrets.Manager(tx, c.UserID)
		names := cur.EnvVars()
		if domain.Truthy(cur.JSONSpec[domain.ContextSigningFlag]) {
			names = append(names, domain.ContextSecretName)
		}
		for _, n := range names {
			if _, err := m.Delete(ctx, domain.InstanceSecretName(cur.ID, n)); err != nil {
				return err
			}
		}
		if owned, err = s.d.Auth.OwnedByConnection(ctx, tx, id); err != nil {
			return err
		}
		for _, a := range owned {
			if a.SecretKey != nil {
				if _, err := m.Delete(ctx, *a.SecretKey); err != nil {
					return err
				}
			}
		}
		if hasSecretRefs(cur.JSONSpec) {
			if err := s.d.Catalog(c.Workspace, actor(c)).StageReferences(ctx, tx, domain.SecretRefConsumer, cur.ID, nil); err != nil {
				return err
			}
		}
		if ok, err := s.d.Instances.Delete(ctx, tx, id); err != nil {
			return err
		} else if !ok {
			return ErrInstanceNotFound()
		}
		if err := s.auditWrite(ctx, tx, c, "mcp_instance.delete", "mcp_instance", cur.ID); err != nil {
			return err
		}
		return events.Publish(ctx, tx, c.UserID, events.NewEnvelope(EventInstanceDeleted, map[string]any{"instance_id": cur.ID}))
	})
	if err != nil {
		return err
	}
	for _, a := range owned {
		if err := s.d.Catalog(c.Workspace, actor(c)).ClearReferences(ctx, "mcp_auth_config", a.ID); err != nil {
			return err
		}
	}
	return nil
}
