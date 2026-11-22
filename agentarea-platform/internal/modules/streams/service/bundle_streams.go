package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// BundleStreams is what a bundle deploy reads and writes of streams.
type BundleStreams struct{ S *Service }

var _ catalogapi.BundleStreams = BundleStreams{}

// bundleRefusal is err as the deploy shows it: the routes' refusals of the input are its own.
func bundleRefusal(err error) error {
	var se *domain.StreamError
	var ve *domain.ValidationError
	switch {
	case err == nil:
		return nil
	case errors.As(err, &se):
		return &catalogapi.BundleRefusal{Msg: se.Msg}
	case errors.As(err, &ve):
		return &catalogapi.BundleRefusal{Msg: ve.Msg}
	case errors.Is(err, ErrSecretForbidden):
		return &catalogapi.BundleRefusal{Msg: err.Error()}
	}
	return err
}

func (b BundleStreams) StreamName(ctx context.Context, id string) (string, bool, error) {
	st, err := b.S.GetStream(ctx, id)
	switch {
	case errors.Is(err, domain.ErrStreamNotFound):
		return "", false, nil
	case err != nil:
		return "", false, err
	}
	return st.Name, true, nil
}

func (b BundleStreams) StreamNamed(ctx context.Context, name string) (string, bool, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return "", false, err
	}
	var st domain.Stream
	var ok bool
	err = b.S.read(ctx, c.Workspace, func(sess db.Session) error {
		st, ok, err = b.S.ss.GetStreamByName(ctx, sess, name)
		return err
	})
	return st.ID, ok, err
}

func writerFilter(w catalogapi.BundleStreamWriter) (domain.EventFilter, error) {
	if w.Filter == nil {
		return domain.ParseEventFilter(nil)
	}
	return domain.ParseEventFilter(w.Filter)
}

func (b BundleStreams) StreamProblem(ctx context.Context, spec catalogapi.BundleStreamSpec) (string, error) {
	if len(spec.Sources) > 0 && !b.S.SourcesReady() {
		return "", errBundleChannelsUnwired
	}
	for _, src := range spec.Sources {
		e, ok, err := b.S.SourceTypeEntry(ctx, src.Type)
		if err != nil {
			return "", err
		}
		if !ok {
			return fmt.Sprintf("source type %s is not in the catalog", domain.PyRepr(src.Type)), nil
		}
		n := newBundleSource(src)
		for k, name := range src.Secrets {
			n.Credentials[k] = Credential{SecretID: &name}
		}
		if err := checkSource(e, n); err != nil {
			return refusalText(err)
		}
	}
	for _, w := range spec.Writers {
		if _, err := writerFilter(w); err != nil {
			return refusalText(err)
		}
		if w.Code != nil {
			if err := domain.CheckProcessorCode(*w.Code); err != nil {
				return refusalText(err)
			}
		}
	}
	return "", nil
}

func refusalText(err error) (string, error) {
	var r *catalogapi.BundleRefusal
	if errors.As(bundleRefusal(err), &r) {
		return r.Msg, nil
	}
	return "", err
}

// newBundleSource is src with its credential values; the secrets are the caller's to add.
func newBundleSource(src catalogapi.BundleStreamSource) NewSource {
	n := NewSource{SourceType: src.Type, Kind: src.Kind, Credentials: map[string]Credential{}, Config: map[string]string{}}
	for k, v := range src.Config {
		n.Config[k] = v
	}
	for k, v := range src.Values {
		n.Credentials[k] = Credential{Value: &v}
	}
	return n
}

// secretIDs are the ids of the workspace secrets names name.
func (b BundleStreams) secretIDs(ctx context.Context, names map[string]string) (map[string]string, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	out := map[string]string{}
	err = b.S.read(ctx, c.Workspace, func(sess db.Session) error {
		for _, name := range names {
			sec, ok, err := b.S.d.Secrets.SecretNamed(ctx, sess, name)
			if err != nil {
				return err
			}
			if !ok {
				return &catalogapi.BundleRefusal{Msg: fmt.Sprintf("workspace secret %s does not exist", domain.PyRepr(name))}
			}
			out[name] = sec.ID
		}
		return nil
	})
	return out, err
}

func (b BundleStreams) addSource(ctx context.Context, streamID string, src catalogapi.BundleStreamSource) error {
	ids, err := b.secretIDs(ctx, src.Secrets)
	if err != nil {
		return err
	}
	n := newBundleSource(src)
	for k, name := range src.Secrets {
		id := ids[name]
		n.Credentials[k] = Credential{SecretID: &id}
	}
	_, _, err = b.S.AddSource(ctx, streamID, n)
	return bundleRefusal(err)
}

func (b BundleStreams) addWriter(ctx context.Context, streamID string, w catalogapi.BundleStreamWriter) error {
	filter, err := writerFilter(w)
	if err != nil {
		return bundleRefusal(err)
	}
	if w.Code != nil {
		_, err = b.S.CreateProcessor(ctx, streamID, w.Outputs, *w.Code, filter)
	} else {
		_, err = b.S.CreateForward(ctx, streamID, w.Outputs, filter)
	}
	return bundleRefusal(err)
}

func (b BundleStreams) CreateStream(ctx context.Context, spec catalogapi.BundleStreamSpec) (string, error) {
	if len(spec.Sources) > 0 && !b.S.SourcesReady() {
		return "", errBundleChannelsUnwired
	}
	st, err := b.S.CreateStream(ctx, spec.Name, spec.Description)
	if err != nil {
		return "", bundleRefusal(err)
	}
	err = func() error {
		for _, src := range spec.Sources {
			if err := b.addSource(ctx, st.ID, src); err != nil {
				return err
			}
		}
		for _, w := range spec.Writers {
			if err := b.addWriter(ctx, st.ID, w); err != nil {
				return err
			}
		}
		return nil
	}()
	if err != nil {
		return "", errors.Join(err, b.S.DeleteStream(context.WithoutCancel(ctx), st.ID))
	}
	return st.ID, nil
}

func (b BundleStreams) DeleteStream(ctx context.Context, id string) error {
	return b.S.DeleteStream(ctx, id)
}

func sameConfig(stored map[string]any, want map[string]string) bool {
	if len(stored) != len(want) {
		return false
	}
	for k, v := range want {
		if s, ok := stored[k].(string); !ok || s != v {
			return false
		}
	}
	return true
}

func sameJSON(a, b any) bool {
	x, err1 := json.Marshal(a)
	y, err2 := json.Marshal(b)
	return err1 == nil && err2 == nil && bytes.Equal(x, y)
}

func sameWriter(sub domain.Subscription, w catalogapi.BundleStreamWriter, filter domain.EventFilter) bool {
	switch {
	case w.Code == nil && sub.Kind != domain.SubForward,
		w.Code != nil && (sub.Kind != domain.SubProcessor || sub.Code == nil || *sub.Code != *w.Code):
		return false
	}
	outputs, err := canonicalOutputs(w.Outputs)
	if err != nil {
		return false
	}
	return slices.Equal(slices.Compact(outputs), sub.OutputStreamIDs) && sameJSON(sub.Filter, filter.Dump())
}

func (b BundleStreams) UpdateStream(ctx context.Context, id string, spec catalogapi.BundleStreamSpec) error {
	st, err := b.S.GetStream(ctx, id)
	if errors.Is(err, domain.ErrStreamNotFound) {
		return catalogapi.ErrBundleEntityGone
	}
	if err != nil {
		return err
	}
	if st.Description != spec.Description {
		if err := b.setDescription(ctx, id, spec.Description); err != nil {
			return err
		}
	}
	if err := b.updateSources(ctx, id, spec.Sources); err != nil {
		return err
	}
	return b.updateWriters(ctx, id, spec.Writers)
}

func (b BundleStreams) setDescription(ctx context.Context, id, description string) error {
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	if err := b.S.perms.Require(ctx, c, "edit", "stream", id); err != nil {
		return err
	}
	return b.S.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		ok, err := b.S.ss.SetDescription(ctx, sess, uuid.MustParse(id), description, b.S.now())
		if err == nil && !ok {
			err = catalogapi.ErrBundleEntityGone
		}
		return err
	})
}

func (b BundleStreams) updateSources(ctx context.Context, id string, want []catalogapi.BundleStreamSource) error {
	if len(want) > 0 && !b.S.SourcesReady() {
		return errBundleChannelsUnwired
	}
	have, err := b.S.ListSources(ctx, id)
	if err != nil {
		return err
	}
	kept := map[string]bool{}
	for _, src := range want {
		i := slices.IndexFunc(have, func(s domain.Source) bool {
			return !kept[s.ID] && s.SourceType != nil && *s.SourceType == src.Type && s.Kind == src.Kind && sameConfig(s.WebhookConfig, src.Config)
		})
		if i < 0 {
			if err := b.addSource(ctx, id, src); err != nil {
				return err
			}
			continue
		}
		kept[have[i].ID] = true
		if err := b.writeCredentials(ctx, have[i], src); err != nil {
			return err
		}
	}
	for _, s := range have {
		if !kept[s.ID] && s.Kind != domain.SourcePlatform {
			if err := b.S.DeleteSource(ctx, id, s.ID); err != nil {
				return bundleRefusal(err)
			}
		}
	}
	return nil
}

// writeCredentials writes src's credentials over the source's own; those it
// does not give stay, and the secret references follow what is stored.
func (b BundleStreams) writeCredentials(ctx context.Context, s domain.Source, src catalogapi.BundleStreamSource) error {
	if len(src.Values) == 0 && len(src.Secrets) == 0 {
		return nil
	}
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	if err := b.S.perms.Require(ctx, c, "edit", "stream", s.StreamID); err != nil {
		return err
	}
	name := CredentialSecretName(*s.SourceType, *s.CredentialKey)
	return b.S.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		m := b.S.d.Secrets.Manager(sess, c.UserID)
		raw, err := m.Get(ctx, name)
		if err != nil && !errors.Is(err, ksecrets.ErrNotFound) {
			return err
		}
		stored := map[string]any{}
		if raw != "" {
			if err := json.Unmarshal([]byte(raw), &stored); err != nil {
				return fmt.Errorf("credentials of source %s are not JSON: %w", s.ID, err)
			}
		}
		merged := make(map[string]any, len(stored))
		for k, v := range stored {
			merged[k] = v
		}
		for k, v := range src.Values {
			merged[k] = v
		}
		for k, secret := range src.Secrets { // pragma: allowlist secret
			sec, ok, err := b.S.d.Secrets.SecretNamed(ctx, sess, secret)
			if err != nil {
				return err
			}
			if !ok {
				return &catalogapi.BundleRefusal{Msg: fmt.Sprintf("workspace secret %s does not exist", domain.PyRepr(secret))}
			}
			usable, err := b.S.usableSecret(ctx, c, sess, sec.ID, k)
			if err != nil {
				return bundleRefusal(err)
			}
			merged[k] = map[string]any{"secret_name": usable}
		}
		if sameJSON(stored, merged) {
			return nil
		}
		keys := make([]string, 0, len(merged))
		for k := range merged {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		var refs []ksecrets.Reference
		for _, k := range keys {
			ref, isRef := merged[k].(map[string]any)
			if !isRef {
				continue
			}
			secret, _ := ref["secret_name"].(string)
			sec, ok, err := b.S.d.Secrets.SecretNamed(ctx, sess, secret)
			if err != nil {
				return err
			}
			if ok {
				refs = append(refs, ksecrets.Reference{SecretID: sec.ID, Field: k})
			}
		}
		body, err := json.Marshal(merged)
		if err != nil {
			return err
		}
		if err := m.Set(ctx, name, string(body)); err != nil {
			return err
		}
		return b.S.d.Secrets.StageReferences(ctx, sess, SecretConsumer, s.ID, refs)
	})
}

func (b BundleStreams) updateWriters(ctx context.Context, id string, want []catalogapi.BundleStreamWriter) error {
	have, err := b.S.ListSubscriptions(ctx, id)
	if err != nil {
		return err
	}
	kept := map[string]bool{}
	for _, w := range want {
		filter, err := writerFilter(w)
		if err != nil {
			return bundleRefusal(err)
		}
		i := slices.IndexFunc(have, func(s domain.Subscription) bool { return !kept[s.ID] && sameWriter(s, w, filter) })
		if i >= 0 {
			kept[have[i].ID] = true
			continue
		}
		if err := b.addWriter(ctx, id, w); err != nil {
			return err
		}
	}
	for _, s := range have {
		if kept[s.ID] {
			continue
		}
		switch s.Kind {
		case domain.SubForward:
			err = b.S.DeleteForward(ctx, id, s.ID)
		case domain.SubProcessor:
			err = b.S.DeleteProcessor(ctx, id, s.ID)
		default:
			continue
		}
		if err != nil {
			return bundleRefusal(err)
		}
	}
	return nil
}
