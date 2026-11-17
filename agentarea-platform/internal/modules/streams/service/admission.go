package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// Telegram is the one identity a source admission links today.
const Telegram = "telegram"

// The link handshake an unlinked sender may run, and how often a refused sender hears why.
const (
	LinkCommand      = "/start link_"
	ConfirmCommand   = "/confirm"
	NoticeInterval   = 24 * time.Hour
	NoticePrefix     = "telegram-sender-notice"
	privateNotice    = "This bot is private."
	telegramBotAPI   = "https://api.telegram.org"
	telegramCallTime = 10 * time.Second
)

// ErrAdmissionUnwired: the process has no sender admission, so nobody gets through.
var ErrAdmissionUnwired = errors.New("no sender admission is wired for this source")

// Door is event_admission's EventAdmission: the admission the event's source type asks for, the
// source whose bot answers, and the source's own choice of who gets through. OwnerID is whoever
// made that choice, "" for a source that never chose.
type Door struct {
	Admission domain.Admission
	Source    domain.Source
	Slug      string
	Senders   domain.Senders
	OwnerID   string
}

// Admitted is who the run of an admitted event is for; Sender names a listed sender the user
// answers for.
type Admitted struct {
	UserID string
	Sender string
}

type telegramSender struct {
	externalID, chatID, text string
	private, isBot           bool
}

func senderOf(a domain.Admission, data map[string]any) (telegramSender, bool) {
	headers := map[string]string{}
	if raw, ok := data["headers"].(map[string]any); ok {
		for k, v := range raw {
			if s, ok := v.(string); ok {
				headers[k] = s
			}
		}
	}
	c := domain.TemplateContext{Body: data["body"], Headers: headers}
	externalID, ok := domain.RenderFirst(a.ExternalID, c)
	if !ok {
		return telegramSender{}, false
	}
	chatID, ok := domain.RenderFirst(a.Chat, c)
	if !ok {
		return telegramSender{}, false
	}
	private, _ := domain.RenderFirst(a.Private, c)
	isBot, _ := domain.RenderFirst(a.IsBot, c)
	text, _ := domain.RenderFirst(a.Text, c)
	return telegramSender{
		externalID: externalID, chatID: chatID, text: strings.TrimSpace(text),
		private: private == a.PrivateValue, isBot: isBot == "true",
	}, true
}

// Admit is TelegramSenderAdmission.admit: the user the event's run is for, or the reason the
// sender is refused. A bot answers "who is this?" and nothing more: an unlinked sender is told
// once a day how to link, a linked one without access that they have none, and group chats and
// other bots are ignored. The link handshake runs first, the one thing an unlinked sender may do.
func (s *Service) Admit(ctx context.Context, ws scope.Workspace, t domain.Trigger, e domain.Event, door Door) (Admitted, string, error) {
	if door.Admission.Identity != Telegram {
		return Admitted{}, fmt.Sprintf("no sender admission links %s accounts", door.Admission.Identity), nil
	}
	if s.d.Links == nil || s.d.Owners == nil || s.d.Notices == nil {
		return Admitted{}, "", ErrAdmissionUnwired
	}
	sender, ok := senderOf(door.Admission, e.Data)
	if !ok {
		return Admitted{}, "the update names no sender", nil
	}
	if sender.isBot {
		return Admitted{}, "the sender is a bot", nil
	}
	if !sender.private {
		return Admitted{}, "only private chats reach the agent", nil
	}
	bot := botOf{s: s, ws: ws, door: door}
	if code, ok := strings.CutPrefix(sender.text, LinkCommand); ok {
		return Admitted{}, "account link requested", s.redeem(ctx, bot, sender, strings.TrimSpace(code))
	}
	if sender.text == ConfirmCommand {
		return Admitted{}, "account link confirmation", s.confirm(ctx, bot, sender)
	}
	var userID, senderKey string
	switch door.Senders.Allow {
	case domain.SendersIDs:
		if !contains(door.Senders.IDs, sender.externalID) {
			return Admitted{}, "the sender is not on the source's list", s.notifyOnce(ctx, t, bot, sender, "private", privateNotice)
		}
		if door.OwnerID == "" {
			return Admitted{}, "the source has no owner to answer for its senders", nil
		}
		userID, senderKey = door.OwnerID, Telegram+":"+sender.externalID
	default:
		holder, linked, err := s.d.Links.Holder(ctx, Telegram, sender.externalID)
		if err != nil {
			return Admitted{}, "", err
		}
		if !linked {
			return Admitted{}, "the sender has not linked their Telegram account",
				s.notifyOnce(ctx, t, bot, sender, "unlinked", s.unlinkedText(ctx, bot))
		}
		if door.Senders.Allow == domain.SendersOwner && holder != door.OwnerID {
			return Admitted{}, fmt.Sprintf("only the source's owner may write; %s is not", holder),
				s.notifyOnce(ctx, t, bot, sender, "private", privateNotice)
		}
		userID = holder
	}
	may, err := s.mayRun(ctx, userID, t.WorkspaceID, t.AgentID)
	if err != nil {
		return Admitted{}, "", err
	}
	if !may {
		return Admitted{}, fmt.Sprintf("user %s may not run agent %s", userID, t.AgentID),
			s.notifyOnce(ctx, t, bot, sender, "denied", "Your account doesn't have access to this agent. Ask its owner to grant it.")
	}
	return Admitted{UserID: userID, Sender: senderKey}, "", nil
}

// mayRun is InvokerAuthority.may_run: the workspace's owner or a member, who holds execute on the agent.
func (s *Service) mayRun(ctx context.Context, userID, workspaceID, agentID string) (bool, error) {
	owner, ok, err := s.d.Owners.Owner(ctx, workspaceID)
	if err != nil {
		return false, err
	}
	if !ok || owner != userID {
		member, err := authz.IsWorkspaceMember(ctx, s.d.Graph, workspaceID, userID)
		if err != nil || !member {
			return false, err
		}
	}
	return s.perms.Check(ctx, authz.UserSubject(userID), "execute", "agent", agentID)
}

func (s *Service) redeem(ctx context.Context, bot botOf, sender telegramSender, code string) error {
	userID, ok, err := s.d.Links.Redeem(ctx, code, Telegram, sender.externalID)
	if err != nil {
		return err
	}
	if !ok {
		bot.reply(ctx, sender, "This link has expired or was already used. Open the link page again for a new one.")
		return nil
	}
	bot.reply(ctx, sender, fmt.Sprintf("Link this Telegram account to %s? Send %s within 10 minutes. "+
		"If you did not ask for this, ignore this message.", s.d.Links.Describe(ctx, userID), ConfirmCommand))
	return nil
}

func (s *Service) confirm(ctx context.Context, bot botOf, sender telegramSender) error {
	userID, ok, err := s.d.Links.Confirm(ctx, Telegram, sender.externalID)
	if errors.Is(err, identityapi.ErrAccountTaken) {
		bot.reply(ctx, sender, "This Telegram account is already linked to another AgentArea account. Unlink it there first.")
		return nil
	}
	if err != nil {
		return err
	}
	if !ok {
		bot.reply(ctx, sender, "There is nothing to confirm.")
		return nil
	}
	bot.reply(ctx, sender, fmt.Sprintf("Done: this Telegram account is linked to %s.", s.d.Links.Describe(ctx, userID)))
	return nil
}

func (s *Service) unlinkedText(ctx context.Context, bot botOf) string {
	url := strings.TrimRight(s.d.AppURL, "/") + "/link/telegram"
	if name := bot.username(ctx); name != "" {
		url += "?bot=" + name
	}
	return "This bot answers only people who linked their Telegram account to AgentArea " +
		"and were given access. Link yours here: " + url
}

func (s *Service) notifyOnce(ctx context.Context, t domain.Trigger, bot botOf, sender telegramSender, kind, text string) error {
	first, err := s.d.Notices.Claim(ctx, t.ID+":"+sender.externalID+":"+kind, NoticeInterval)
	if err != nil {
		return err
	}
	if first {
		bot.reply(ctx, sender, text)
	}
	return nil
}

// botOf is the bot that answers a sender: the one whose token the source stores. A reply that
// cannot be sent is logged; the sender stays refused either way.
type botOf struct {
	s    *Service
	ws   scope.Workspace
	door Door
}

func (b botOf) token(ctx context.Context) string {
	key := ""
	if b.door.Source.CredentialKey != nil {
		key = *b.door.Source.CredentialKey
	}
	creds, err := b.s.SourceCredentials(ctx, b.ws, b.door.Source.CreatedBy, b.door.Slug, key)
	if err != nil {
		b.s.log.ErrorContext(ctx, "The source's Telegram credentials cannot be read", "source_id", b.door.Source.ID, "error", err.Error())
		return ""
	}
	if creds["bot_token"] == "" {
		b.s.log.ErrorContext(ctx, "The source has no Telegram bot token", "source_id", b.door.Source.ID)
	}
	return creds["bot_token"]
}

func (b botOf) call(ctx context.Context, token, method string, payload any) (*http.Response, error) {
	if b.s.d.Out == nil {
		return nil, errors.New("outbound HTTP is not wired")
	}
	ctx, cancel := context.WithTimeout(ctx, telegramCallTime)
	defer cancel()
	verb, body := http.MethodGet, io.Reader(nil)
	if payload != nil {
		raw, err := json.Marshal(payload)
		if err != nil {
			return nil, err
		}
		verb, body = http.MethodPost, bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, verb, telegramBotAPI+"/bot"+token+"/"+method, body)
	if err != nil {
		return nil, err
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := (&http.Client{Transport: b.s.d.Out.Transport(netguard.Vendor)}).Do(req)
	if err != nil {
		return nil, err
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	_ = resp.Body.Close()
	resp.Body = io.NopCloser(bytes.NewReader(raw))
	return resp, err
}

func (b botOf) username(ctx context.Context) string {
	token := b.token(ctx)
	if token == "" {
		return ""
	}
	resp, err := b.call(ctx, token, "getMe", nil)
	if err != nil {
		b.s.log.WarnContext(ctx, "Telegram getMe failed", "error", err.Error())
		return ""
	}
	if resp.StatusCode/100 != 2 {
		b.s.log.WarnContext(ctx, "Telegram getMe failed", "status", resp.StatusCode)
		return ""
	}
	var me struct {
		Result struct {
			Username string `json:"username"`
		} `json:"result"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&me); err != nil {
		b.s.log.WarnContext(ctx, "Telegram getMe answered no JSON", "error", err.Error())
		return ""
	}
	return me.Result.Username
}

func (b botOf) reply(ctx context.Context, sender telegramSender, text string) {
	token := b.token(ctx)
	if token == "" {
		return
	}
	resp, err := b.call(ctx, token, "sendMessage", map[string]any{"chat_id": sender.chatID, "text": text})
	if err != nil {
		b.s.log.WarnContext(ctx, "Could not reply to a Telegram sender", "error", err.Error())
		return
	}
	if resp.StatusCode/100 != 2 {
		b.s.log.WarnContext(ctx, "Telegram sendMessage failed", "status", resp.StatusCode)
	}
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
