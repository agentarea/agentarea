package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// releaseSource drops what a source holds outside its row: its credentials and their references
// (_stream_sources.release_source), inside the caller's transaction.
func (s *Service) releaseSource(ctx context.Context, sess db.Session, c authn.Caller, src domain.Source) error {
	if src.SourceType == nil || src.CredentialKey == nil || s.d.Secrets == nil {
		return nil
	}
	if _, err := s.d.Secrets.Manager(sess, c.UserID).Delete(ctx, CredentialSecretName(*src.SourceType, *src.CredentialKey)); err != nil {
		return err
	}
	return s.d.Secrets.StageReferences(ctx, sess, SecretConsumer, src.ID, nil)
}

// SubscriberSecretName is where an external subscriber's signing secret is stored.
func SubscriberSecretName(externalID string) string { return "mcp_events_whsec:" + externalID }

// releaseSubscriberSecrets drops the secrets of the stream's external subscribers
// (release_subscriber_secrets), inside the caller's transaction.
func (s *Service) releaseSubscriberSecrets(ctx context.Context, sess db.Session, c authn.Caller, subs []domain.Subscription) error {
	if s.d.Secrets == nil {
		return nil
	}
	m := s.d.Secrets.Manager(sess, c.UserID)
	for _, sub := range subs {
		if sub.ExternalID == nil || *sub.ExternalID == "" {
			continue
		}
		if _, err := m.Delete(ctx, SubscriberSecretName(*sub.ExternalID)); err != nil {
			return err
		}
	}
	return nil
}
