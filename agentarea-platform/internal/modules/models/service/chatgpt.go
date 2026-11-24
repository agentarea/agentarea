package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

const (
	// chatGPTRefreshMargin renews an access token this long before it expires.
	chatGPTRefreshMargin = 5 * time.Minute
	// chatGPTDeviceCodeTTL is how long the issuer honours a device code.
	chatGPTDeviceCodeTTL = 15 * time.Minute
	// chatGPTSaveBudget bounds a renewal or a sign-in's save once the issuer
	// has rotated the tokens; the caller going away does not cut it short.
	chatGPTSaveBudget = time.Minute
)

// ChatGPTDeviceCodeSeconds is how long a started sign-in's code is valid.
const ChatGPTDeviceCodeSeconds = int(chatGPTDeviceCodeTTL / time.Second)

func (s *Service) chatGPT() transport.ChatGPTAuth {
	return transport.ChatGPTAuth{Issuer: s.d.ChatGPTIssuer, Transport: s.d.Out.Transport(netguard.Vendor), Now: s.d.Now}
}

func signsIn(auth string) bool { return auth == domain.AuthChatGPT }

// chatOnly refuses a non-chat call on a ChatGPT sign-in before its secret is read.
func chatOnly(m api.ResolvedModel) error {
	return &api.ModelCallError{Msg: fmt.Sprintf("model instance %s runs on a ChatGPT subscription, which serves chat calls only", m.ModelID)}
}

func noEndpointForChatGPT() error {
	return &BadRequestError{Detail: "A ChatGPT subscription is called at its own address; endpoint_url cannot be set"}
}

// chatGPTConfig is the caller's own configuration of a ChatGPT sign-in provider.
func (s *Service) chatGPTConfig(ctx context.Context, id uuid.UUID) (scope.Workspace, string, error) {
	ws, userID, err := caller(ctx)
	if err != nil {
		return scope.Workspace{}, "", err
	}
	if err := s.admin(ctx); err != nil {
		return scope.Workspace{}, "", err
	}
	v, ok, err := s.view(ctx, ws, id)
	if err != nil {
		return scope.Workspace{}, "", err
	}
	if !ok || v.PlatformManaged() {
		return scope.Workspace{}, "", &HTTPError{Status: 404, Detail: "Provider configuration not found"}
	}
	if v.Spec == nil || !signsIn(v.Spec.Auth) {
		return scope.Workspace{}, "", &BadRequestError{Detail: "This provider does not sign in with ChatGPT"}
	}
	return ws, userID, nil
}

// StartChatGPTSignIn starts a device-code login for the configuration. The
// device code stays here, bound to the caller and the configuration; only the
// code the user types leaves.
func (s *Service) StartChatGPTSignIn(ctx context.Context, id uuid.UUID) (transport.DeviceCode, error) {
	ws, userID, err := s.chatGPTConfig(ctx, id)
	if err != nil {
		return transport.DeviceCode{}, err
	}
	d, err := s.chatGPT().StartDeviceCode(ctx)
	if err != nil {
		return transport.DeviceCode{}, err
	}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return s.st.PutSignIn(ctx, sess, domain.SignIn{ConfigID: id.String(), UserID: userID,
			DeviceAuthID: d.DeviceAuthID, UserCode: d.UserCode, ExpiresAt: s.d.Now().Add(chatGPTDeviceCodeTTL)})
	})
	return d, err
}

// FinishChatGPTSignIn checks the caller's pending sign-in on the configuration;
// once the user entered the code, the configuration holds the new token set
// and the answer is true.
func (s *Service) FinishChatGPTSignIn(ctx context.Context, id uuid.UUID) (bool, error) {
	ws, userID, err := s.chatGPTConfig(ctx, id)
	if err != nil {
		return false, err
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return false, err
	}
	pending, ok, err := s.st.SignIn(ctx, sess, id, userID)
	release()
	if err != nil {
		return false, err
	}
	if !ok || !pending.ExpiresAt.After(s.d.Now()) {
		return false, &BadRequestError{Detail: "No ChatGPT sign-in of yours is pending on this configuration; start it again"}
	}
	t, done, err := s.chatGPT().PollDeviceCode(ctx, pending.DeviceAuthID, pending.UserCode)
	if err != nil || !done {
		return false, err
	}
	dctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), chatGPTSaveBudget)
	defer cancel()
	err = s.d.DB.Write(dctx, ws, func(ctx context.Context, sess db.Session) error {
		c, ok, err := s.st.Config(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &HTTPError{Status: 404, Detail: "Provider configuration not found"}
		}
		name := domain.OwnSecretName(c.ID)
		if err := s.d.Secrets.Manager(sess, userID).Set(ctx, name, t.Encode()); err != nil {
			return err
		}
		c.APIKey = &name
		if c.APIKeySecretID, err = s.secretIDFor(ctx, sess, name); err != nil {
			return err
		}
		if err := s.registerReference(ctx, sess, c); err != nil {
			return err
		}
		if _, err := s.st.UpdateConfig(ctx, sess, c, s.d.Now()); err != nil {
			return err
		}
		return s.st.DeleteSignIn(ctx, sess, id, userID)
	})
	if err != nil {
		slog.ErrorContext(ctx, "ChatGPT sign-in finished at the issuer but was not saved; sign in again",
			"provider_config_id", id.String(), "error", err)
		return false, err
	}
	return true, nil
}

// chatGPTAccess is the token set a call uses: the stored one while it is
// fresh, else one renewal under the configuration's row lock, so two calls
// never spend the same rotating refresh token.
func (s *Service) chatGPTAccess(ctx context.Context, ws scope.Workspace, userID, secretName, stored string) (transport.ChatGPTTokens, error) {
	configID, ok := strings.CutPrefix(secretName, domain.OwnSecretName(""))
	id, perr := uuid.Parse(configID)
	if stored == "" || !ok || perr != nil {
		return transport.ChatGPTTokens{}, transport.SignInError("this provider is not signed in")
	}
	t, err := transport.ParseChatGPTTokens(stored)
	if err != nil {
		return transport.ChatGPTTokens{}, err
	}
	if t.Fresh(s.d.Now(), chatGPTRefreshMargin) {
		return t, nil
	}
	dctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), chatGPTSaveBudget)
	defer cancel()
	rotated := false
	err = s.d.DB.Write(dctx, ws, func(ctx context.Context, sess db.Session) error {
		held, err := s.st.LockConfig(ctx, sess, id)
		if err != nil {
			return err
		}
		if !held {
			return transport.SignInError("the provider configuration is gone")
		}
		m := s.d.Secrets.Manager(sess, userID)
		cur, err := m.Get(ctx, secretName)
		if errors.Is(err, ksecrets.ErrNotFound) {
			return transport.SignInError("this provider is not signed in")
		}
		if err != nil {
			return err
		}
		if t, err = transport.ParseChatGPTTokens(cur); err != nil {
			return err
		}
		if t.Fresh(s.d.Now(), chatGPTRefreshMargin) {
			return nil
		}
		if t, err = s.chatGPT().Refresh(ctx, t); err != nil {
			return err
		}
		rotated = true
		return m.Set(ctx, secretName, t.Encode())
	})
	switch {
	case err == nil:
		return t, nil
	case rotated:
		slog.ErrorContext(ctx, "ChatGPT sign-in was renewed but the new tokens were not saved; the configuration must sign in again",
			"provider_config_id", id.String(), "error", err)
	case errors.Is(err, store.ErrLockBusy):
		if cur, rerr := s.readSecret(ctx, ws, userID, secretName); rerr == nil {
			if nt, perr := transport.ParseChatGPTTokens(cur); perr == nil && nt.Fresh(s.d.Now(), chatGPTRefreshMargin) {
				return nt, nil
			}
		}
		return transport.ChatGPTTokens{}, &transport.PyError{Type: "TimeoutError",
			Msg: "timed out: another call is renewing this provider's ChatGPT sign-in", Cause: err}
	}
	return transport.ChatGPTTokens{}, err
}
