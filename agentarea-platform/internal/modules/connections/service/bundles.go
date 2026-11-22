package service

import (
	"context"
	"errors"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// BundleMCPs is what a bundle deploy reads and writes of MCP connections; S
// is the service in force.
type BundleMCPs struct{ S func() *Service }

var _ catalogapi.BundleMCPs = BundleMCPs{}

// bundleRefusalText is the MCPValidationError or PermissionError text, "" for any other error.
func bundleRefusalText(err error) string {
	var invalid *domain.SpecInvalid
	var forbidden *domain.Forbidden
	switch {
	case errors.As(err, &invalid):
		return strings.Join(invalid.Errors, "; ")
	case errors.As(err, &forbidden):
		return forbidden.Msg
	}
	return ""
}

func bundleRefusal(err error) error {
	if msg := bundleRefusalText(err); msg != "" {
		return &catalogapi.BundleRefusal{Msg: msg}
	}
	return err
}

func (b BundleMCPs) InstanceName(ctx context.Context, c authn.Caller, id string) (string, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return "", false, nil
	}
	inst, err := b.S().GetInstance(ctx, c, u)
	var nf *domain.NotFound
	switch {
	case errors.As(err, &nf):
		return "", false, nil
	case err != nil:
		return "", false, err
	}
	return inst.Name, true, nil
}

func created(v InstanceView, err error) (catalogapi.BundleMCPCreated, error) {
	if err != nil {
		return catalogapi.BundleMCPCreated{}, bundleRefusal(err)
	}
	return catalogapi.BundleMCPCreated{InstanceID: v.Instance.ID, SpecID: v.Instance.ServerSpecID}, nil
}

func instanceCreate(in catalogapi.BundleInstance) InstanceCreate {
	return InstanceCreate{Name: in.Name, JSONSpec: in.JSONSpec, ContextSecret: in.ContextSecret}
}

func (b BundleMCPs) CreateFromSpec(ctx context.Context, c authn.Caller, specID string, in catalogapi.BundleInstance) (catalogapi.BundleMCPCreated, error) {
	n := instanceCreate(in)
	n.ServerSpecID = specID
	return created(b.S().CreateInstance(ctx, c, n))
}

func (b BundleMCPs) CreateWithSpec(ctx context.Context, c authn.Caller, spec catalogapi.MCPSpecNew, in catalogapi.BundleInstance) (catalogapi.BundleMCPCreated, error) {
	return created(b.S().CreateInstanceWithSpec(ctx, c, spec, instanceCreate(in)))
}

func (BundleMCPs) KeepSecret() any { return domain.MaskedValue }

func specTransport(sp catalogapi.MCPSpec) map[string]any {
	return domain.ServerTransportSpec(sp.JSONSpec, sp.RemoteURL, sp.Cmd, sp.DockerImageURL)
}

// UpdateMCP applies a redeploy: the spec, with a container whose transport
// moves retired first, then the instance's name, environment, headers and context secret.
func (b BundleMCPs) UpdateMCP(ctx context.Context, c authn.Caller, id string, u catalogapi.BundleMCPUpdate) error {
	s := b.S()
	iid, err := uuid.Parse(id)
	if err != nil {
		return catalogapi.ErrBundleEntityGone
	}
	inst, err := s.GetInstance(ctx, c, iid)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return catalogapi.ErrBundleEntityGone
	}
	if err != nil {
		return err
	}
	name := u.Instance.Name
	p := InstancePatchIn{Name: &name, JSONSpec: u.Instance.JSONSpec}
	if p.JSONSpec == nil {
		p.JSONSpec = map[string]any{}
	}
	if u.SetContextSecret {
		p.ContextSecretSet, p.ContextSecret = true, u.Instance.ContextSecret
	}
	if u.Spec != nil {
		n := *u.Spec
		before, ok, err := s.MCPSpec(ctx, c, inst.ServerSpecID)
		if err != nil {
			return err
		}
		if !ok {
			return catalogapi.ErrBundleEntityGone
		}
		next := before
		next.JSONSpec, next.RemoteURL, next.Cmd, next.DockerImageURL = n.JSONSpec, n.RemoteURL, n.Cmd, n.DockerImageURL
		if domain.IsContainer(inst.Transport) && !sameJSON(specTransport(before), specTransport(next)) {
			_, retiresItself, err := s.planSpecUpdate(ctx, c, inst, p.JSONSpec)
			if err != nil {
				return bundleRefusal(err)
			}
			if !retiresItself {
				if err := s.retire(ctx, inst.ID); err != nil {
					return err
				}
			}
		}
		_, err = s.UpdateSpec(ctx, c, inst.ServerSpecID, SpecPatch{
			Set: map[string]bool{"name": true, "description": true, "env_schema": true, "json_spec": true, "cmd": true,
				"docker_image_url": true, "remote_url": true},
			Name: n.Name, Description: n.Description, EnvSchema: n.EnvSchema, JSONSpec: n.JSONSpec, Cmd: n.Cmd,
			DockerImageURL: n.DockerImageURL, RemoteURL: n.RemoteURL})
		if err != nil {
			return bundleRefusal(err)
		}
	}
	_, err = s.UpdateInstance(ctx, c, iid, p)
	if errors.As(err, &nf) {
		return catalogapi.ErrBundleEntityGone
	}
	return bundleRefusal(err)
}

// Rediscover verifies the instance again: the tools it stores are the ones it serves now.
func (b BundleMCPs) Rediscover(ctx context.Context, c authn.Caller, id string) (catalogapi.BundleDiscovery, error) {
	iid, err := uuid.Parse(id)
	if err != nil {
		return catalogapi.BundleDiscovery{}, catalogapi.ErrBundleEntityGone
	}
	tools, v, err := b.S().DiscoverInstanceTools(ctx, c.Workspace, iid)
	if err != nil {
		return catalogapi.BundleDiscovery{}, err
	}
	out := catalogapi.BundleDiscovery{Status: v.Status, Tools: len(tools)}
	if v.Error != nil && v.Error.Message != "" {
		msg := v.Error.Message
		out.Error = &msg
	}
	return out, nil
}

func (b BundleMCPs) DeleteInstance(ctx context.Context, c authn.Caller, id string) error {
	u, err := uuid.Parse(id)
	if err != nil {
		return err
	}
	return b.S().DeleteInstance(ctx, c, u)
}

func (b BundleMCPs) DeleteSpec(ctx context.Context, c authn.Caller, id string) error {
	return b.S().DeleteSpec(ctx, c, id)
}

func (b BundleMCPs) SecretProblem(ctx context.Context, c authn.Caller, name string) (string, error) {
	_, err := b.S().secretRefs(ctx, c, map[string]string{name: name})
	if err == nil {
		return "", nil
	}
	if msg := bundleRefusalText(err); msg != "" {
		return msg, nil
	}
	return "", err
}

func (BundleMCPs) CarriesSecretRef(v any) bool { return domain.CarriesSecretRef(v) }

func (BundleMCPs) SecretRef(name string) any { return map[string]any{domain.SecretRefKey: name} }

func (BundleMCPs) ContextSecretLength() (minimum, maximum int) {
	return domain.ContextSecretMinLength, domain.ContextSecretMaxLength
}

func (BundleMCPs) SpecTransport(spec catalogapi.MCPSpec) (string, bool) {
	t, _ := domain.ServerTransportSpec(spec.JSONSpec, spec.RemoteURL, spec.Cmd, spec.DockerImageURL)["type"].(string)
	switch t {
	case domain.TransportURL, domain.TransportCommand, domain.TransportDocker, domain.TransportBundle:
		return t, true
	}
	return "", false
}
