package service

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

// chatGPTRefreshMargin renews an access token this long before it expires.
const chatGPTRefreshMargin = 5 * time.Minute

func (s *Service) chatGPT() transport.ChatGPTAuth {
	return transport.ChatGPTAuth{Issuer: s.d.ChatGPTIssuer, Transport: s.d.Out.Transport(netguard.Vendor), Now: s.d.Now}
}

// chatGPTConfig is the caller's own configuration of a ChatGPT sign-in provider.
func (s *Service) chatGPTConfig(ctx context.Context, id uuid.UUID) (ConfigView, error) {
	ws, _, err := caller(ctx)
	if err != nil {
		return ConfigView{}, err
	}
	if err := s.admin(ctx); err != nil {
		return ConfigView{}, err
	}
	v, ok, err := s.view(ctx, ws, id)
	if err != nil {
		return ConfigView{}, err
	}
	if !ok || v.PlatformManaged() {
		return ConfigView{}, &HTTPError{Status: 404, Detail: "Provider configuration not found"}
	}
	if v.Spec == nil || v.Spec.Auth != domain.AuthChatGPT {
		return ConfigView{}, &BadRequestError{Detail: "This provider does not sign in with ChatGPT"}
	}
	return v, nil
}

// StartChatGPTSignIn starts a device-code login for the configuration.
func (s *Service) StartChatGPTSignIn(ctx context.Context, id uuid.UUID) (transport.DeviceCode, error) {
	if _, err := s.chatGPTConfig(ctx, id); err != nil {
		return transport.DeviceCode{}, err
	}
	return s.chatGPT().StartDeviceCode(ctx)
}

// FinishChatGPTSignIn checks the device code; once the user entered it, the
// configuration holds the new token set and the answer is true.
func (s *Service) FinishChatGPTSignIn(ctx context.Context, id uuid.UUID, deviceAuthID, userCode string) (bool, error) {
	if _, err := s.chatGPTConfig(ctx, id); err != nil {
		return false, err
	}
	t, done, err := s.chatGPT().PollDeviceCode(ctx, deviceAuthID, userCode)
	if err != nil || !done {
		return false, err
	}
	encoded := t.Encode()
	_, found, err := s.UpdateConfig(ctx, id, domain.ConfigPatch{APIKey: domain.Opt[string]{Set: true, Value: &encoded}})
	if err == nil && !found {
		err = &HTTPError{Status: 404, Detail: "Provider configuration not found"}
	}
	return err == nil, err
}

// chatGPTAccess is the token set a call uses: the stored one while it is
// fresh, else one refresh under the configuration's row lock, so two calls
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
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
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
		return m.Set(ctx, secretName, t.Encode())
	})
	if err != nil {
		return transport.ChatGPTTokens{}, err
	}
	return t, nil
}
