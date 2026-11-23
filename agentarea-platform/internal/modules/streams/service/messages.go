package service

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/replies"
)

// ErrMessagesUnwired: the process has no messenger links or outbound clients to send with.
var ErrMessagesUnwired = errors.New("sending messages needs the messenger links and the outbound clients, which this process was not given")

// messengerBot is a stream's source whose bot can write to a linked account.
type messengerBot struct {
	stream domain.Stream
	source domain.Source
	slug   string
}

// SendMessage is messages_send_message: in.Text to the Telegram account member in.UserID linked,
// by the bot of a messenger stream the caller may read; in.Stream names it, "" takes the only
// one. The chat is always the account the member linked, never one the caller names.
func (s *Service) SendMessage(ctx context.Context, in api.MessageSend) (api.MessageSent, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return api.MessageSent{}, err
	}
	if s.d.Links == nil || s.d.Out == nil {
		return api.MessageSent{}, ErrMessagesUnwired
	}
	bots, err := s.messengerBots(ctx, c, in.Stream)
	if err != nil {
		return api.MessageSent{}, err
	}
	switch {
	case len(bots) == 0 && in.Stream != "":
		return api.MessageSent{}, domain.Refused(fmt.Sprintf("Stream %s has no Telegram source to write from", domain.PyRepr(in.Stream)))
	case len(bots) == 0:
		return api.MessageSent{}, domain.Refused("The workspace has no messenger stream you can write from: " +
			"add a Telegram source to a stream first")
	}
	accounts, err := s.d.Links.Accounts(ctx, in.UserID, Telegram)
	if err != nil {
		return api.MessageSent{}, err
	}
	if len(accounts) == 0 {
		return api.MessageSent{}, domain.Refused(fmt.Sprintf("%s has not linked a Telegram account, so no message can reach them. "+
			"They link it by writing to the bot of stream %s in Telegram and opening the link it answers with",
			in.Recipient, domain.PyRepr(bots[0].stream.Name)))
	}
	if len(bots) > 1 {
		names := make([]string, len(bots))
		for i, b := range bots {
			names[i] = domain.PyRepr(b.stream.Name)
		}
		return api.MessageSent{}, domain.Refused(fmt.Sprintf("Several messenger streams reach %s: %s; name one in stream",
			in.Recipient, strings.Join(names, ", ")))
	}
	bot := bots[0]
	key := ""
	if bot.source.CredentialKey != nil {
		key = *bot.source.CredentialKey
	}
	creds, err := s.SourceCredentials(ctx, c.Workspace, bot.source.CreatedBy, bot.slug, key)
	if err != nil {
		return api.MessageSent{}, err
	}
	if creds["bot_token"] == "" {
		return api.MessageSent{}, domain.Refused(fmt.Sprintf("The Telegram source of stream %s has no bot token", domain.PyRepr(bot.stream.Name)))
	}
	tg := replies.TelegramLive{Client: &http.Client{Transport: s.d.Out.Transport(netguard.Vendor)}}
	id, cut, err := tg.Message(ctx, creds["bot_token"], accounts[0], in.Text)
	var refused *replies.TelegramRefused
	if errors.As(err, &refused) && refused.Status == http.StatusForbidden {
		return api.MessageSent{}, domain.Refused(fmt.Sprintf("Telegram refused the message: %s. %s must open the bot of stream %s "+
			"in Telegram and press Start (or unblock it) before it can write to them", refused.Description, in.Recipient, domain.PyRepr(bot.stream.Name)))
	}
	if errors.As(err, &refused) {
		return api.MessageSent{}, domain.Refused(refused.Error())
	}
	if err != nil {
		return api.MessageSent{}, err
	}
	s.log.InfoContext(ctx, "Message sent to a workspace member", "stream_id", bot.stream.ID, "source_id", bot.source.ID,
		"user_id", in.UserID, "agent_id", agentOf(c))
	return api.MessageSent{Sent: true, To: in.Recipient, Stream: api.StreamRef{ID: bot.stream.ID, Name: bot.stream.Name},
		Messenger: Telegram, MessageID: &id, Truncated: cut}, nil
}

func agentOf(c authn.Caller) string {
	if c.Subject != nil && c.Subject.Kind == authn.SubjectAgent {
		return c.Subject.ID
	}
	return ""
}

// messengerBots are the Telegram sources of the stream ref names, the caller holding read on it,
// or, for "", of every stream the caller may read, at most one per stream: its first.
func (s *Service) messengerBots(ctx context.Context, c authn.Caller, ref string) ([]messengerBot, error) {
	var streams []domain.Stream
	if ref == "" {
		ids, err := s.readable(ctx, c)
		if err != nil {
			return nil, err
		}
		err = s.read(ctx, c.Workspace, func(sess db.Session) error {
			streams, err = s.ss.ListStreams(ctx, sess, ids, StreamListLimit, 0)
			return err
		})
		if err != nil {
			return nil, err
		}
	} else {
		var found domain.Stream
		err := s.read(ctx, c.Workspace, func(sess db.Session) error {
			var err error
			found, err = s.findStream(ctx, sess, ref)
			return err
		})
		if err != nil {
			return nil, err
		}
		if err := s.perms.Require(ctx, c, "read", "stream", found.ID); err != nil {
			return nil, err
		}
		streams = []domain.Stream{found}
	}
	messenger := map[string]bool{}
	var out []messengerBot
	err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		for _, st := range streams {
			sources, err := s.ss.ListSources(ctx, sess, uuid.MustParse(st.ID))
			if err != nil {
				return err
			}
			for _, src := range sources {
				if src.SourceType == nil {
					continue
				}
				slug := *src.SourceType
				is, known := messenger[slug]
				if !known {
					e, ok, err := s.SourceTypeEntry(ctx, slug)
					if err != nil {
						return err
					}
					is = ok && e.Admission != nil && e.Admission.Identity == Telegram
					messenger[slug] = is
				}
				if is {
					out = append(out, messengerBot{stream: st, source: src, slug: slug})
					break
				}
			}
		}
		return nil
	})
	return out, err
}
