package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"path"
	"strconv"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
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
	files, err := s.runFiles(ctx, c, in)
	if err != nil {
		return api.MessageSent{}, err
	}
	page := ""
	for _, f := range files {
		if f.size <= replies.TelegramUploadLimit {
			continue
		}
		if page, err = s.taskPage(ctx, c, in.TaskID); err != nil {
			return api.MessageSent{}, err
		}
		if page == "" {
			return api.MessageSent{}, tooLargeToSend(f.path)
		}
		break
	}
	tg := replies.TelegramLive{Client: &http.Client{Transport: s.d.Out.Transport(netguard.Vendor)}}
	var id int64
	var cut bool
	if strings.TrimSpace(in.Text) != "" {
		id, cut, err = tg.Message(ctx, creds["bot_token"], accounts[0], in.Text)
	}
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
	var sent, linked []string
	link := func(f runFileRef, size int64) error {
		if page == "" {
			var err error
			if page, err = s.taskPage(ctx, c, in.TaskID); err != nil {
				return err
			}
		}
		if page == "" {
			return tooLargeToSend(f.path)
		}
		if _, _, err := tg.Message(ctx, creds["bot_token"], accounts[0], replies.LinkedFile(path.Base(f.path), size, replies.TaskFileURL(page, f.path))); err != nil {
			return err
		}
		linked = append(linked, f.path)
		return nil
	}
	for _, f := range files {
		if f.size > replies.TelegramUploadLimit {
			if err := link(f, f.size); err != nil {
				return api.MessageSent{}, err
			}
			continue
		}
		data, ct, err := s.readRunFile(ctx, c, in.TaskID, f.path)
		if errors.Is(err, errRunFileTooLarge) {
			if err := link(f, f.size); err != nil {
				return api.MessageSent{}, err
			}
			continue
		}
		if err != nil {
			return api.MessageSent{}, err
		}
		err = tg.File(ctx, creds["bot_token"], accounts[0], path.Base(f.path), ct, data)
		var refusedFile *replies.FileRefused
		if errors.As(err, &refusedFile) && refusedFile.TooLarge {
			if err := link(f, int64(len(data))); err != nil {
				return api.MessageSent{}, err
			}
			continue
		}
		if errors.As(err, &refusedFile) {
			return api.MessageSent{}, domain.Refused(fmt.Sprintf("Telegram refused %s: %s (sent before it: %v)", f.path, refusedFile.Description, sent))
		}
		if err != nil {
			return api.MessageSent{}, err
		}
		sent = append(sent, f.path)
	}
	s.log.InfoContext(ctx, "Message sent to a workspace member", "stream_id", bot.stream.ID, "source_id", bot.source.ID,
		"user_id", in.UserID, "agent_id", agentOf(c))
	out := api.MessageSent{Sent: true, To: in.Recipient, Stream: api.StreamRef{ID: bot.stream.ID, Name: bot.stream.Name},
		Messenger: Telegram, Truncated: cut, Files: sent, Linked: linked}
	if id != 0 {
		out.MessageID = &id
	}
	return out, nil
}

// MaxMessageFiles is how many files one send_message sends.
const MaxMessageFiles = 10

// runFileRef is a checked file of the run; size is what the sandbox reports, -1 when it does not.
type runFileRef struct {
	path string
	size int64
}

var errRunFileTooLarge = errors.New("run file is larger than a Telegram bot sends")

// runFiles checks the files in.Files names before anything is sent: each a path in the run's
// workspace, and there. It answers the normalized paths with their sizes; nothing is read yet.
func (s *Service) runFiles(ctx context.Context, c authn.Caller, in api.MessageSend) ([]runFileRef, error) {
	if len(in.Files) == 0 {
		return nil, nil
	}
	if in.TaskID == "" {
		return nil, domain.Refused("files can be sent only from a run: they are paths of the run's own files")
	}
	if len(in.Files) > MaxMessageFiles {
		return nil, domain.Refused(fmt.Sprintf("at most %d files go in one message, %d given", MaxMessageFiles, len(in.Files)))
	}
	if s.d.TaskFiles == nil {
		return nil, ErrMessagesUnwired
	}
	out := make([]runFileRef, 0, len(in.Files))
	for _, raw := range in.Files {
		p := strings.TrimPrefix(strings.TrimPrefix(strings.TrimSpace(raw), "/workspace/"), "./")
		clean := path.Clean(p)
		if p == "" || strings.HasPrefix(clean, "/") || clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
			return nil, domain.Refused(fmt.Sprintf("%s is not a path in the run's workspace, such as outputs/report.pdf", domain.PyRepr(raw)))
		}
		d, err := s.openRunFile(ctx, c, in.TaskID, clean)
		if err != nil {
			return nil, err
		}
		_ = d.Body.Close()
		size := int64(-1)
		if n, err := strconv.ParseInt(d.Header.Get("Content-Length"), 10, 64); err == nil {
			size = n
		}
		out = append(out, runFileRef{path: clean, size: size})
	}
	return out, nil
}

func tooLargeToSend(p string) error {
	return domain.Refused(fmt.Sprintf("%s is larger than the 50 MB a Telegram bot sends", p))
}

// taskPage is the run's page in the webapp; empty when the webapp or the workspace's slug is unknown.
func (s *Service) taskPage(ctx context.Context, c authn.Caller, taskID string) (string, error) {
	if s.d.AppURL == "" {
		return "", nil
	}
	slug := c.Workspace.Slug()
	if slug == "" || slug == c.Workspace.ID() {
		if s.d.Slugs == nil {
			return "", nil
		}
		var err error
		if slug, err = s.d.Slugs.Slug(ctx, c.Workspace.ID()); errors.Is(err, identityapi.ErrWorkspaceNotFound) {
			return "", nil
		} else if err != nil {
			return "", err
		}
	}
	return replies.TaskPageURL(s.d.AppURL, slug, taskID), nil
}

func (s *Service) openRunFile(ctx context.Context, c authn.Caller, taskID, p string) (sandboxapi.Download, error) {
	d, err := s.d.TaskFiles.ReadFile(ctx, c.Workspace.ID(), taskID, p, false)
	var tfe *sandboxapi.TaskFileError
	if errors.As(err, &tfe) && tfe.Status < 500 {
		return d, domain.Refused(fmt.Sprintf("%s cannot be read: %s", p, tfe.Detail))
	}
	return d, err
}

// readRunFile reads one checked file, at most Telegram's upload limit, and its type.
func (s *Service) readRunFile(ctx context.Context, c authn.Caller, taskID, p string) ([]byte, string, error) {
	d, err := s.openRunFile(ctx, c, taskID, p)
	if err != nil {
		return nil, "", err
	}
	defer func() { _ = d.Body.Close() }()
	data, err := io.ReadAll(io.LimitReader(d.Body, replies.TelegramUploadLimit+1))
	if err != nil {
		return nil, "", err
	}
	if len(data) > replies.TelegramUploadLimit {
		return nil, "", errRunFileTooLarge
	}
	ct := d.Header.Get("Content-Type")
	if ct == "" || strings.HasPrefix(ct, "application/octet-stream") {
		ct = mime.TypeByExtension(strings.ToLower(path.Ext(p)))
	}
	return data, ct, nil
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
