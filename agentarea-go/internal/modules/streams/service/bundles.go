package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	ksecrets "github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// BundleTriggers is what a bundle deploy reads and writes of triggers and channel streams.
type BundleTriggers struct{ S *Service }

var _ catalogapi.BundleTriggers = BundleTriggers{}

var errBundleChannelsUnwired = errors.New("streams: channels need the source catalog, secrets and the secret catalog wired")

const bundleFailureThreshold = 5

func bundleTrigger(t domain.Trigger) catalogapi.BundleTrigger {
	out := catalogapi.BundleTrigger{ID: t.ID, Name: t.Name, AgentID: t.AgentID, Active: t.IsActive}
	if t.Binding != nil {
		id := t.Binding.StreamID
		out.StreamID = &id
	}
	return out
}

func (b BundleTriggers) Trigger(ctx context.Context, id string) (catalogapi.BundleTrigger, bool, error) {
	t, err := b.S.Get(ctx, id)
	switch {
	case errors.Is(err, domain.ErrNotFound):
		return catalogapi.BundleTrigger{}, false, nil
	case err != nil:
		return catalogapi.BundleTrigger{}, false, err
	}
	return bundleTrigger(t), true, nil
}

func (b BundleTriggers) Triggers(ctx context.Context) ([]catalogapi.BundleTrigger, error) {
	ts, err := b.S.List(ctx, store.Filter{Limit: math.MaxInt32})
	if err != nil {
		return nil, err
	}
	out := make([]catalogapi.BundleTrigger, len(ts))
	for i, t := range ts {
		out[i] = bundleTrigger(t)
	}
	return out, nil
}

func cronTrigger(n catalogapi.BundleCron) domain.NewTrigger {
	cron, tz := n.Cron, n.Timezone
	return domain.NewTrigger{Name: n.Name, Description: n.Description, AgentID: n.AgentID, Type: domain.TypeCron,
		CronExpression: &cron, Timezone: &tz, TaskParameters: map[string]any{"text": n.Text}, Enabled: n.Enabled,
		FailureThreshold: bundleFailureThreshold}
}

func (b BundleTriggers) CronProblem(_ context.Context, n catalogapi.BundleCron) (string, error) {
	_, _, err := b.S.validateNew(cronTrigger(n))
	var invalid *domain.ValidationError
	switch {
	case err == nil:
		return "", nil
	case errors.As(err, &invalid):
		return invalid.Msg, nil
	}
	return "", err
}

func (b BundleTriggers) CreateCron(ctx context.Context, n catalogapi.BundleCron) (string, error) {
	t, err := b.S.Create(ctx, cronTrigger(n))
	return t.ID, err
}

func (b BundleTriggers) CreateChannel(ctx context.Context, n catalogapi.BundleChannelNew) (catalogapi.BundleChannelCreated, error) {
	if !b.S.SourcesReady() {
		return catalogapi.BundleChannelCreated{}, errBundleChannelsUnwired
	}
	entry, ok, err := b.S.SourceTypeEntry(ctx, n.SourceType)
	if err != nil {
		return catalogapi.BundleChannelCreated{}, err
	}
	if !ok {
		return catalogapi.BundleChannelCreated{}, &catalogapi.BundleRefusal{Msg: fmt.Sprintf("channel type %s is not in the catalog", domain.PyRepr(n.SourceType))}
	}
	st, err := b.S.CreateStream(ctx, n.Name, n.Description)
	if err != nil {
		return catalogapi.BundleChannelCreated{}, err
	}
	creds := make(map[string]Credential, len(n.Credentials))
	for k, v := range n.Credentials {
		creds[k] = Credential{Value: &v}
	}
	_, _, err = b.S.AddSource(ctx, st.ID, NewSource{SourceType: entry.Slug, Kind: domain.SourceWebhook, Credentials: creds, Config: map[string]string{}})
	var t domain.Trigger
	if err == nil {
		streamID := st.ID
		t, err = b.S.Create(ctx, domain.NewTrigger{Name: n.Name, Description: n.Description, AgentID: n.AgentID, Type: domain.TypeStream,
			StreamID: &streamID, TaskParameters: map[string]any{"text": n.Text}, Enabled: n.Enabled, FailureThreshold: bundleFailureThreshold})
	}
	if err != nil {
		if derr := b.S.DeleteStream(context.WithoutCancel(ctx), st.ID); derr != nil {
			return catalogapi.BundleChannelCreated{}, errors.Join(err, derr)
		}
		return catalogapi.BundleChannelCreated{}, err
	}
	return catalogapi.BundleChannelCreated{TriggerID: t.ID, StreamID: st.ID}, nil
}

func (b BundleTriggers) DeleteChannel(ctx context.Context, created catalogapi.BundleChannelCreated) error {
	return errors.Join(b.S.Delete(ctx, created.TriggerID), b.S.DeleteStream(ctx, created.StreamID))
}

func (b BundleTriggers) DeleteTrigger(ctx context.Context, id string) error {
	return b.S.Delete(ctx, id)
}

func (b BundleTriggers) UpdateTrigger(ctx context.Context, id string, u catalogapi.BundleTriggerUpdate) error {
	desc, agent := u.Description, u.AgentID
	_, err := b.S.Update(ctx, id, Patch{Description: &desc, AgentID: &agent, TaskParameters: map[string]any{"text": u.Text},
		CronExpression: u.Cron, Timezone: u.Timezone})
	return err
}

func (b BundleTriggers) SetTriggerEnabled(ctx context.Context, id string, enabled bool) error {
	t, err := b.S.Get(ctx, id)
	if err != nil || t.IsActive == enabled {
		return err
	}
	if enabled {
		_, err = b.S.Enable(ctx, id)
	} else {
		_, err = b.S.Disable(ctx, id)
	}
	return err
}

func (b BundleTriggers) ChannelCredentials(ctx context.Context, triggerID string) (catalogapi.BundleChannelCredentials, bool, error) {
	none := catalogapi.BundleChannelCredentials{}
	if !b.S.SourcesReady() {
		return none, false, errBundleChannelsUnwired
	}
	t, err := b.S.Get(ctx, triggerID)
	switch {
	case errors.Is(err, domain.ErrNotFound):
		return none, false, nil
	case err != nil:
		return none, false, err
	}
	if t.Binding == nil {
		return none, false, nil
	}
	sources, err := b.S.ListSources(ctx, t.Binding.StreamID)
	if err != nil {
		return none, false, err
	}
	var out catalogapi.BundleChannelCredentials
	found := false
	for _, src := range sources {
		if src.SourceType != nil && *src.SourceType != "" && src.CredentialKey != nil && *src.CredentialKey != "" {
			out, found = catalogapi.BundleChannelCredentials{SourceType: *src.SourceType, CredentialKey: *src.CredentialKey}, true
			break
		}
	}
	if !found {
		return none, false, nil
	}
	c, err := callerOf(ctx)
	if err != nil {
		return none, false, err
	}
	var raw string
	err = b.S.read(ctx, c.Workspace, func(sess db.Session) error {
		var gerr error
		raw, gerr = b.S.d.Secrets.Manager(sess, c.UserID).Get(ctx, CredentialSecretName(out.SourceType, out.CredentialKey))
		if errors.Is(gerr, ksecrets.ErrNotFound) {
			raw, gerr = "", nil
		}
		return gerr
	})
	if err != nil {
		return none, false, err
	}
	out.Stored = map[string]any{}
	if raw != "" {
		var v any
		if jerr := json.Unmarshal([]byte(raw), &v); jerr != nil {
			return none, false, fmt.Errorf("channel credentials of trigger %s are not JSON: %w", triggerID, jerr)
		}
		if m, ok := v.(map[string]any); ok {
			out.Stored = m
		}
	}
	return out, true, nil
}

func (b BundleTriggers) SetChannelCredentials(ctx context.Context, creds catalogapi.BundleChannelCredentials) error {
	if !b.S.SourcesReady() {
		return errBundleChannelsUnwired
	}
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	body, err := json.Marshal(creds.Stored)
	if err != nil {
		return err
	}
	return b.S.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		return b.S.d.Secrets.Manager(sess, c.UserID).Set(ctx, CredentialSecretName(creds.SourceType, creds.CredentialKey), string(body))
	})
}
