package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// LookupTimeout bounds an api_lookup read of the provider's API.
const LookupTimeout = 10 * time.Second

const maxLookupBody = 10 << 20

// ErrProviderUnreachable is the provider's API not answering an api_lookup; the sender retries.
var ErrProviderUnreachable = errors.New("provider unreachable")

// WebhookAnswer is the status and JSON body the sink answers a delivery with.
type WebhookAnswer struct {
	Status int
	Body   any
}

func answerError(status int, msg string) WebhookAnswer {
	return WebhookAnswer{Status: status, Body: map[string]any{"status": "error", "message": msg}}
}

// providerLookup reads the notified object back from a provider (api_lookup) as the source's member.
func (s *Service) providerLookup(ctx context.Context, method, rawURL string, auth *domain.BasicAuth) (int, any, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return 0, nil, &domain.VerificationError{Msg: "the lookup URL is not a URL"}
	}
	for _, seg := range strings.Split(u.Path, "/") {
		if seg == ".." {
			return 0, nil, &domain.VerificationError{Msg: "the lookup URL climbs out of its path"}
		}
	}
	if s.d.Out == nil {
		return 0, nil, fmt.Errorf("%w: no outbound client", ErrProviderUnreachable)
	}
	ctx, cancel := context.WithTimeout(ctx, LookupTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, method, u.String(), nil)
	if err != nil {
		return 0, nil, &domain.VerificationError{Msg: "the lookup request cannot be made: " + err.Error()}
	}
	if auth != nil {
		req.SetBasicAuth(auth.Username, auth.Password)
	}
	client := &http.Client{
		Transport:     s.d.Out.Transport(netguard.Vendor),
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	resp, err := client.Do(req)
	if err != nil {
		return 0, nil, fmt.Errorf("%w: %w", ErrProviderUnreachable, err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxLookupBody))
	if err != nil {
		return 0, nil, fmt.Errorf("%w: %w", ErrProviderUnreachable, err)
	}
	body, err := DecodeJSON(raw)
	if err != nil {
		return resp.StatusCode, nil, nil
	}
	return resp.StatusCode, body, nil
}

// WebhookDelivery is one request to the webhook sink, its body read and parsed.
type WebhookDelivery struct {
	WebhookID string
	Headers   map[string]string
	Raw       []byte
	Body      any
}

// HandleWebhook is WebhookSourceIntake.handle_webhook_request: the source by its webhook id, the
// request verified by its entry's scheme with the source's credentials, a handshake answered, a
// signal acted on, and anything else recorded as one event (202 accepted or duplicate).
func (s *Service) HandleWebhook(ctx context.Context, d WebhookDelivery) (WebhookAnswer, error) {
	receivedAt := s.now()
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return WebhookAnswer{}, err
	}
	src, ok, err := s.ss.FindWebhookSource(ctx, q, d.WebhookID)
	release()
	if err != nil {
		return WebhookAnswer{}, err
	}
	if !ok {
		return answerError(http.StatusNotFound, fmt.Sprintf("Webhook %s not found", d.WebhookID)), nil
	}
	slug := ""
	if src.SourceType != nil {
		slug = *src.SourceType
	}
	entry, found, err := s.SourceTypeEntry(ctx, slug)
	if err != nil {
		return WebhookAnswer{}, err
	}
	if !found {
		s.log.ErrorContext(ctx, "Webhook source type is not in the catalog", "webhook_id", d.WebhookID, "slug", slug)
		return answerError(http.StatusBadRequest, fmt.Sprintf("Source type %s is not in the catalog", domain.PyRepr(slug))), nil
	}
	if entry.Verification == nil {
		s.log.ErrorContext(ctx, "Webhook source type verifies no webhook", "webhook_id", d.WebhookID, "slug", slug)
		return answerError(http.StatusBadRequest, fmt.Sprintf("Source type %s does not take webhooks", domain.PyRepr(slug))), nil
	}
	if src.CredentialKey == nil {
		return WebhookAnswer{}, fmt.Errorf("webhook source %s is stored without a credential key", src.ID)
	}
	ws, err := workspaceOf(src)
	if err != nil {
		return WebhookAnswer{}, err
	}
	var answer WebhookAnswer
	err = s.read(ctx, ws, func(sess db.Session) error {
		answer, err = s.deliver(ctx, sess, d, src, entry, receivedAt)
		return err
	})
	return answer, err
}

func (s *Service) deliver(ctx context.Context, sess db.Session, d WebhookDelivery, src domain.Source, entry domain.SourceTypeEntry,
	receivedAt time.Time,
) (WebhookAnswer, error) {
	body, refused, err := s.verifyDelivery(ctx, sess, d, src, entry)
	if refused != nil || err != nil {
		return derefAnswer(refused), err
	}
	if answer, ok := domain.HandshakeAnswer(entry, d.Headers, body); ok {
		return WebhookAnswer{Status: http.StatusOK, Body: answer}, nil
	}
	signal, err := domain.SignalOf(entry, d.Headers, body)
	if err != nil {
		s.log.WarnContext(ctx, "Webhook refused", "webhook_id", d.WebhookID, "error", err.Error())
		return answerError(http.StatusBadRequest, err.Error()), nil
	}
	if signal != nil && signal.Signal == "ended" {
		id, err := uuid.Parse(src.ID)
		if err != nil {
			return WebhookAnswer{}, err
		}
		err = s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			return s.ss.EndSourceSubscription(ctx, q, id, signal.Reason, s.now())
		})
		if err != nil {
			return WebhookAnswer{}, err
		}
		s.log.WarnContext(ctx, "Webhook source subscription ended", "webhook_id", d.WebhookID, "reason", signal.Reason)
		return WebhookAnswer{Status: http.StatusOK, Body: map[string]any{"status": "ended"}}, nil
	}
	in := intake{src: src, entry: entry, body: body, headers: d.Headers, receivedAt: receivedAt}
	if signal != nil {
		in.kindOverride, in.keyOverride = domain.GapKind, signal.Key
	}
	r, err := s.ingest(ctx, sess, in)
	var se *domain.StreamError
	switch {
	case err == nil:
	case errors.Is(err, domain.ErrQuotaExceeded):
		return answerError(http.StatusTooManyRequests, err.Error()), nil
	case errors.Is(err, domain.ErrStreamNotFound):
		return answerError(http.StatusNotFound, err.Error()), nil
	case errors.As(err, &se):
		return answerError(http.StatusBadRequest, err.Error()), nil
	default:
		s.log.ErrorContext(ctx, "Webhook could not be recorded", "webhook_id", d.WebhookID, "stream_id", src.StreamID, "error", err.Error())
		return answerError(http.StatusServiceUnavailable, "The webhook could not be recorded; retry the delivery"), nil
	}
	status := "accepted"
	if !r.Appended {
		status = "duplicate"
	}
	return WebhookAnswer{Status: http.StatusAccepted, Body: map[string]any{"status": status, "event_id": r.EventID}}, nil
}

func derefAnswer(a *WebhookAnswer) WebhookAnswer {
	if a == nil {
		return WebhookAnswer{}
	}
	return *a
}

// verifyDelivery is the body to record, or the refusal to answer: 503 when it cannot be verified
// now, 401 when it does not verify.
func (s *Service) verifyDelivery(ctx context.Context, sess db.Session, d WebhookDelivery, src domain.Source, entry domain.SourceTypeEntry,
) (any, *WebhookAnswer, error) {
	unreachable := func(err error) (any, *WebhookAnswer, error) {
		s.log.ErrorContext(ctx, "Webhook could not be verified now", "webhook_id", d.WebhookID, "error", err.Error())
		a := answerError(http.StatusServiceUnavailable, "The webhook could not be verified now; retry the delivery")
		return nil, &a, nil
	}
	refused := func(err error) (any, *WebhookAnswer, error) {
		s.log.WarnContext(ctx, "Webhook refused", "webhook_id", d.WebhookID, "error", err.Error())
		a := answerError(http.StatusUnauthorized, "Verification failed")
		return nil, &a, nil
	}
	creds, err := s.sourceCredentials(ctx, sess, src.CreatedBy, *src.SourceType, *src.CredentialKey)
	switch {
	case errors.Is(err, ErrSecretStoreUnreachable):
		return unreachable(err)
	case errors.Is(err, ErrCredentialsUnavailable):
		return refused(err)
	case err != nil:
		return nil, nil, err
	}
	scheme, err := domain.Configured(*entry.Verification, src.WebhookConfig)
	if err != nil {
		return refused(err)
	}
	config := src.WebhookConfig
	if config == nil {
		config = map[string]any{}
	}
	body, err := domain.Verify(ctx, scheme, d.Headers, d.Raw, d.Body, creds, config, s.providerLookup, s.now())
	var ve *domain.VerificationError
	switch {
	case err == nil:
		return body, nil, nil
	case errors.Is(err, ErrProviderUnreachable):
		return unreachable(err)
	case errors.As(err, &ve):
		return refused(err)
	}
	return nil, nil, err
}

// WebhookHealthy is the webhook manager's health: always healthy.
func (s *Service) WebhookHealthy() bool { return true }
