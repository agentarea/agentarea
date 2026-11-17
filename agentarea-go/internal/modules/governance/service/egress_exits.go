package service

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/store"
)

// UpstreamNotAllowed is UPSTREAM_NOT_ALLOWED.
const UpstreamNotAllowed = "upstream_url must be a public address this deployment may reach"

const egressExitResource = "egress_exit"

// EgressExitInvalidError is EgressExitValidationError, and a password secret
// that is not there: 400.
type EgressExitInvalidError struct{ Msg string }

func (e *EgressExitInvalidError) Error() string { return e.Msg }

// EgressExitForbiddenError is PlatformEgressExitError, and a password secret
// the caller may not use: 403.
type EgressExitForbiddenError struct{ Msg string }

func (e *EgressExitForbiddenError) Error() string { return e.Msg }

// EgressExitInUseError is EgressExitInUseError: 409.
type EgressExitInUseError struct{ Msg string }

func (e *EgressExitInUseError) Error() string { return e.Msg }

var _ api.EgressExitBinding = (*Service)(nil)

// EgressExitNew is EgressExitCreate, validated.
type EgressExitNew struct {
	Name                      string
	Description               *string
	UpstreamURL               string
	Username                  *string
	PasswordSecretID          *string
	AllowPlaintextCredentials bool
}

// EgressExitPatch is EgressExitUpdate's sent fields: *string for the string
// and UUID ones, *bool for allow_plaintext_credentials; nil was null.
type EgressExitPatch map[string]any

func egressRouteFields() []string {
	return []string{"upstream_url", "username", "password_secret_id", "allow_plaintext_credentials"}
}

func (sv *Service) egress() (*EgressExitPorts, error) {
	p := sv.d.EgressExits
	switch {
	case p == nil:
		return nil, api.ErrEgressExitsUnsupported
	case p.Graph == nil:
		return nil, errors.New("egress exits need the authorization graph")
	case p.Instances == nil || p.Upstream == nil:
		return nil, errors.New("egress exits need the MCP instances and the outbound address policy")
	}
	return p, nil
}

// EgressExitsEnforced reports whether the edition enforces egress exits.
func (sv *Service) EgressExitsEnforced() bool { return sv.d.EgressExits != nil }

// ListEgressExits is the workspace's own exits, newest first.
func (sv *Service) ListEgressExits(ctx context.Context, c authn.Caller) ([]domain.EgressExit, error) {
	p, err := sv.egress()
	if err != nil {
		return nil, err
	}
	s, done, err := sv.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer done()
	return p.Store.List(ctx, s)
}

// GetEgressExit is one of the workspace's exits.
func (sv *Service) GetEgressExit(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.EgressExit, error) {
	p, err := sv.egress()
	if err != nil {
		return domain.EgressExit{}, err
	}
	s, done, err := sv.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return domain.EgressExit{}, err
	}
	defer done()
	return getEgressExit(ctx, p, s, id)
}

func getEgressExit(ctx context.Context, p *EgressExitPorts, s db.Session, id uuid.UUID) (domain.EgressExit, error) {
	e, found, err := p.Store.Get(ctx, s, id)
	if err != nil {
		return domain.EgressExit{}, err
	}
	if !found {
		return domain.EgressExit{}, &api.EgressExitNotFoundError{ID: id.String()}
	}
	return e, nil
}

// RequireBindable is require_bindable: the exit an instance of the caller's
// workspace asks to leave through, if the caller may use it.
func (sv *Service) RequireBindable(ctx context.Context, c authn.Caller, exitID string) error {
	p, err := sv.egress()
	if err != nil {
		return err
	}
	id, err := uuid.Parse(exitID)
	if err != nil {
		return &api.EgressExitNotFoundError{ID: exitID}
	}
	s, done, err := sv.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return err
	}
	e, err := getEgressExit(ctx, p, s, id)
	done()
	if err != nil {
		var nf *api.EgressExitNotFoundError
		if errors.As(err, &nf) {
			nf.ID = exitID
		}
		return err
	}
	if e.IsPlatform() {
		return nil
	}
	return authz.NewPermissions(p.Graph, sv.d.Log).Require(ctx, c, "use", egressExitResource, e.ID)
}

// RequireOnEgressExit is route_authz.requires(permission, "egress_exit").
func (sv *Service) RequireOnEgressExit(ctx context.Context, c authn.Caller, permission, id string) error {
	p, err := sv.egress()
	if err != nil {
		return err
	}
	return authz.NewPermissions(p.Graph, sv.d.Log).Require(ctx, c, permission, egressExitResource, id)
}

// assertUpstreamPublic is _assert_upstream_public: the proxy address the
// egress proxy would dial, refused at save time when it may not.
func (sv *Service) assertUpstreamPublic(ctx context.Context, p *EgressExitPorts, upstream string) error {
	_, netloc, _ := strings.Cut(upstream, "://")
	err := p.Upstream(ctx, "http://"+netloc)
	if errors.Is(err, netguard.ErrUnsafe) {
		sv.d.Log.InfoContext(ctx, "Refused egress exit upstream_url on save", "error", err)
		return &EgressExitInvalidError{Msg: UpstreamNotAllowed}
	}
	return err
}

// passwordForUse is catalog.get_for_use as the router maps its refusals.
func (sv *Service) passwordForUse(ctx context.Context, cat secrets.Catalog, id string) error {
	_, err := cat.GetForUse(ctx, id)
	switch {
	case errors.Is(err, secrets.ErrNotFound):
		return &EgressExitInvalidError{Msg: err.Error()}
	case errors.Is(err, secrets.ErrAccessDenied), errors.Is(err, secrets.ErrManaged):
		return &EgressExitForbiddenError{Msg: err.Error()}
	}
	return err
}

func (sv *Service) egressCatalog(c authn.Caller) (secrets.Catalog, error) {
	if sv.d.Secrets == nil {
		return nil, errors.New("egress exits need the secret catalog")
	}
	return sv.catalog(c), nil
}

func passwordRefs(secretID *string) []secrets.Reference {
	if secretID == nil {
		return []secrets.Reference{}
	}
	return []secrets.Reference{{SecretID: *secretID, Field: "password"}}
}

// CreateEgressExit defines a proxy the workspace's MCP instances may leave
// through, the caller's in the graph.
func (sv *Service) CreateEgressExit(ctx context.Context, c authn.Caller, in EgressExitNew) (domain.EgressExit, error) {
	p, err := sv.egress()
	if err != nil {
		return domain.EgressExit{}, err
	}
	cat, err := sv.egressCatalog(c)
	if err != nil {
		return domain.EgressExit{}, err
	}
	if err := sv.assertUpstreamPublic(ctx, p, in.UpstreamURL); err != nil {
		return domain.EgressExit{}, err
	}
	if in.PasswordSecretID != nil {
		if err := sv.passwordForUse(ctx, cat, *in.PasswordSecretID); err != nil {
			return domain.EgressExit{}, err
		}
	}
	id := uuid.NewString()
	var created domain.EgressExit
	err = sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		if err := cat.StageReferences(ctx, s, egressExitResource, id, passwordRefs(in.PasswordSecretID)); err != nil {
			return err
		}
		e, err := p.Store.Create(ctx, s, domain.EgressExit{ID: id, Name: in.Name, Description: in.Description,
			UpstreamURL: &in.UpstreamURL, Username: in.Username, PasswordSecretID: in.PasswordSecretID,
			AllowPlaintextCredentials: in.AllowPlaintextCredentials, CreatedBy: c.UserID}, sv.d.Now())
		if err != nil {
			return err
		}
		if err := authz.GrantResourceOwner(ctx, p.Graph, id, c.Workspace.ID(), c.GraphSubject(), authz.OwnerRelations()); err != nil {
			return err
		}
		sv.recordEgress(ctx, s, c, "egress_exit.create", id, nil)
		created = e
		return nil
	})
	return created, err
}

// requireOwnEgressExit is _require_own.
func requireOwnEgressExit(ctx context.Context, p *EgressExitPorts, s db.Session, id uuid.UUID) (domain.EgressExit, error) {
	e, err := getEgressExit(ctx, p, s, id)
	if err != nil {
		return domain.EgressExit{}, err
	}
	if e.IsPlatform() {
		return domain.EgressExit{}, &EgressExitForbiddenError{Msg: "Egress exit " + id.String() + " is the platform's; it is not changed through the API"}
	}
	return e, nil
}

func egressColumn(e domain.EgressExit, field string) any {
	switch field {
	case "name":
		return &e.Name
	case "description":
		return e.Description
	case "upstream_url":
		return e.UpstreamURL
	case "username":
		return e.Username
	case "password_secret_id":
		return e.PasswordSecretID
	case "allow_plaintext_credentials":
		return &e.AllowPlaintextCredentials
	}
	panic("egress exit has no patchable column " + field)
}

func sameColumn(a, b any) bool {
	switch x := a.(type) {
	case *string:
		y := b.(*string)
		return (x == nil) == (y == nil) && (x == nil || *x == *y)
	case *bool:
		y := b.(*bool)
		return (x == nil) == (y == nil) && (x == nil || *x == *y)
	}
	return false
}

// UpdateEgressExit changes the sent fields; a new route retires every running
// container instance bound to the exit before it is stored.
func (sv *Service) UpdateEgressExit(ctx context.Context, c authn.Caller, id uuid.UUID, patch EgressExitPatch) (domain.EgressExit, error) {
	p, err := sv.egress()
	if err != nil {
		return domain.EgressExit{}, err
	}
	var updated domain.EgressExit
	err = sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		current, err := requireOwnEgressExit(ctx, p, s, id)
		if err != nil {
			return err
		}
		for _, required := range []string{"name", "upstream_url", "allow_plaintext_credentials"} {
			if v, sent := patch[required]; sent && isNull(v) {
				return &EgressExitInvalidError{Msg: required + " cannot be cleared"}
			}
		}
		changes := store.EgressExitChanges{}
		for k, v := range patch {
			if !sameColumn(egressColumn(current, k), v) {
				changes[k] = v
			}
		}
		if len(changes) == 0 {
			sv.recordEgress(ctx, s, c, "egress_exit.update", id.String(), domain.AuditChanges(current, current))
			updated = current
			return nil
		}
		next := current
		applyEgressChanges(&next, changes)
		if errs := domain.CredentialErrors(next.UpstreamURL, next.Username, next.PasswordSecretID, next.AllowPlaintextCredentials); len(errs) > 0 {
			return &EgressExitInvalidError{Msg: strings.Join(errs, "; ")}
		}
		if _, ok := changes["upstream_url"]; ok {
			if err := sv.assertUpstreamPublic(ctx, p, *next.UpstreamURL); err != nil {
				return err
			}
		}
		newPassword, passwordSent := changes["password_secret_id"]
		var cat secrets.Catalog
		if passwordSent {
			if cat, err = sv.egressCatalog(c); err != nil {
				return err
			}
			if pw := newPassword.(*string); pw != nil {
				if err := sv.passwordForUse(ctx, cat, *pw); err != nil {
					return err
				}
			}
		}
		if slices.ContainsFunc(egressRouteFields(), func(f string) bool { _, ok := changes[f]; return ok }) {
			if err := sv.retireBound(ctx, p, c, id); err != nil {
				return err
			}
		}
		if passwordSent {
			if err := cat.StageReferences(ctx, s, egressExitResource, id.String(), passwordRefs(newPassword.(*string))); err != nil {
				return err
			}
		}
		e, found, err := p.Store.Update(ctx, s, id, changes, sv.d.Now())
		if err != nil {
			return err
		}
		if !found {
			return &api.EgressExitNotFoundError{ID: id.String()}
		}
		sv.recordEgress(ctx, s, c, "egress_exit.update", id.String(), domain.AuditChanges(current, e))
		updated = e
		return nil
	})
	return updated, err
}

func isNull(v any) bool {
	switch x := v.(type) {
	case *string:
		return x == nil
	case *bool:
		return x == nil
	}
	return v == nil
}

func applyEgressChanges(e *domain.EgressExit, changes store.EgressExitChanges) {
	for k, v := range changes {
		switch k {
		case "name":
			e.Name = *v.(*string)
		case "description":
			e.Description = v.(*string)
		case "upstream_url":
			e.UpstreamURL = v.(*string)
		case "username":
			e.Username = v.(*string)
		case "password_secret_id":
			e.PasswordSecretID = v.(*string)
		case "allow_plaintext_credentials":
			e.AllowPlaintextCredentials = *v.(*bool)
		}
	}
}

// retireBound retires every running container instance that leaves through
// the exit: it holds the route it started with.
func (sv *Service) retireBound(ctx context.Context, p *EgressExitPorts, c authn.Caller, id uuid.UUID) error {
	bound, err := p.Instances.BoundToEgressExit(ctx, c.Workspace, id.String())
	if err != nil {
		return err
	}
	for _, i := range bound {
		if i.Transport != "docker" && i.Transport != "command" {
			continue
		}
		if err := p.Instances.RetireBeforeMutation(ctx, i.ID); err != nil {
			return err
		}
	}
	return nil
}

// DeleteEgressExit deletes an exit no MCP instance leaves through.
func (sv *Service) DeleteEgressExit(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	p, err := sv.egress()
	if err != nil {
		return err
	}
	cat, err := sv.egressCatalog(c)
	if err != nil {
		return err
	}
	err = sv.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, s db.Session) error {
		if _, err := requireOwnEgressExit(ctx, p, s, id); err != nil {
			return err
		}
		bound, err := p.Instances.BoundToEgressExit(ctx, c.Workspace, id.String())
		if err != nil {
			return err
		}
		if len(bound) > 0 {
			names := make([]string, len(bound))
			for i, b := range bound {
				names[i] = b.Name
			}
			sort.Strings(names)
			return &EgressExitInUseError{Msg: fmt.Sprintf("%d MCP instance(s) leave through this exit (%s); unbind them before deleting it",
				len(bound), strings.Join(names, ", "))}
		}
		if err := cat.StageReferences(ctx, s, egressExitResource, id.String(), passwordRefs(nil)); err != nil {
			return err
		}
		deleted, err := p.Store.Delete(ctx, s, id)
		if err != nil {
			return err
		}
		if !deleted {
			return &api.EgressExitNotFoundError{ID: id.String()}
		}
		sv.recordEgress(ctx, s, c, "egress_exit.delete", id.String(), nil)
		return nil
	})
	if err != nil {
		return err
	}
	if err := authz.RevokeResource(ctx, p.Graph, id.String()); err != nil {
		sv.d.Log.ErrorContext(ctx, "Deleted EgressExit but could not remove its graph tuples", "egress_exit_id", id.String(), "error", err)
	}
	return nil
}

// recordEgress is @audited's recording for egress_exit: a failure is logged.
func (sv *Service) recordEgress(ctx context.Context, s db.Session, c authn.Caller, action, id string, changes []map[string]any) {
	if err := sv.record(ctx, s, c, action, egressExitResource, &id, changes, nil); err != nil {
		sv.d.Log.WarnContext(ctx, "Failed to record audit event", "action", action, "resource_type", egressExitResource, "error", err)
	}
}
