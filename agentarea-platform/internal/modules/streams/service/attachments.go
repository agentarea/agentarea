package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	kblob "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

// TelegramDownloadLimit is the largest file the Bot API lets a bot download (getFile).
const TelegramDownloadLimit = 20 << 20

// URLDownloadLimit is the largest file a plain url or slack.url_private fetch brings.
const URLDownloadLimit = 50 << 20

const fetchTimeout = 2 * time.Minute

// FetchedFile is a file an event named by reference, brought: its bytes, its type when the source
// says, and a name when the event gave none.
type FetchedFile struct {
	Data        []byte
	ContentType string
	Name        string
}

// AttachmentFetcher brings a file an event names by reference: one fetch of a source type's
// event.attachments. item is the file object as the event carries it, creds the source's credentials.
type AttachmentFetcher interface {
	// Limit is the largest file it brings.
	Limit() int64
	Fetch(ctx context.Context, creds map[string]string, item map[string]any) (FetchedFile, error)
}

// ErrFileTooLarge is a file larger than its fetch brings.
var ErrFileTooLarge = errors.New("file is too large to fetch")

// fetchRefused is a fetch no retry brings: the file is gone or the source refuses it.
type fetchRefused struct{ msg string }

func (e *fetchRefused) Error() string { return e.msg }

func refusedFetch(format string, a ...any) error {
	return &fetchRefused{msg: fmt.Sprintf(format, a...)}
}

func (s *Service) fetchers() map[string]AttachmentFetcher {
	if s.d.Fetchers != nil {
		return s.d.Fetchers
	}
	if s.d.Out == nil {
		return nil
	}
	vendor := &http.Client{Transport: s.d.Out.Transport(netguard.Vendor)}
	public := &http.Client{Transport: s.d.Out.Transport(netguard.Public)}
	return map[string]AttachmentFetcher{
		"telegram.getFile":  TelegramFiles{Client: vendor},
		"slack.url_private": URLFiles{Client: public, Token: "bot_token", Keys: []string{"url_private_download", "url_private"}},
		"url":               URLFiles{Client: public, Keys: []string{"url", "proxy_url"}},
	}
}

// TelegramFiles is telegram.getFile: the file's path from getFile, then the file itself.
type TelegramFiles struct {
	// Client calls the Bot API; API is its base, https://api.telegram.org when empty.
	Client *http.Client
	API    string
}

func (TelegramFiles) Limit() int64 { return TelegramDownloadLimit }

func (t TelegramFiles) Fetch(ctx context.Context, creds map[string]string, item map[string]any) (FetchedFile, error) {
	token := creds["bot_token"]
	if token == "" {
		return FetchedFile{}, refusedFetch("the source's credentials have no bot_token")
	}
	fileID, _ := item["file_id"].(string)
	if fileID == "" {
		return FetchedFile{}, refusedFetch("the file names no file_id")
	}
	base := t.API
	if base == "" {
		base = "https://api.telegram.org"
	}
	status, body, err := get(ctx, t.Client, base+"/bot"+token+"/getFile?file_id="+url.QueryEscape(fileID), nil, 1<<20)
	if err != nil {
		return FetchedFile{}, err
	}
	var answer struct {
		OK          bool   `json:"ok"`
		Description string `json:"description"`
		Result      struct {
			FilePath string `json:"file_path"`
		} `json:"result"`
	}
	_ = json.Unmarshal(body, &answer)
	switch {
	case status == http.StatusBadRequest && strings.Contains(strings.ToLower(answer.Description), "too big"):
		return FetchedFile{}, ErrFileTooLarge
	case status == http.StatusTooManyRequests || status >= 500:
		return FetchedFile{}, fmt.Errorf("telegram getFile answered %d: %s", status, answer.Description)
	case !answer.OK || answer.Result.FilePath == "":
		return FetchedFile{}, refusedFetch("Telegram refused the file (%d): %s", status, answer.Description)
	}
	status, data, err := get(ctx, t.Client, base+"/file/bot"+token+"/"+answer.Result.FilePath, nil, TelegramDownloadLimit)
	if err != nil {
		return FetchedFile{}, err
	}
	if err := downloadStatus(status); err != nil {
		return FetchedFile{}, err
	}
	return FetchedFile{Data: data, Name: path.Base(answer.Result.FilePath)}, nil
}

// URLFiles is a file the event names by a URL (url, slack.url_private): the first of Keys the item
// has, with the credential Token names as a bearer token when set.
type URLFiles struct {
	Client *http.Client
	Token  string
	Keys   []string
}

func (URLFiles) Limit() int64 { return URLDownloadLimit }

func (u URLFiles) Fetch(ctx context.Context, creds map[string]string, item map[string]any) (FetchedFile, error) {
	var link string
	for _, k := range u.Keys {
		if v, ok := item[k].(string); ok && v != "" {
			link = v
			break
		}
	}
	if link == "" {
		return FetchedFile{}, refusedFetch("the file names no URL")
	}
	header := http.Header{}
	if u.Token != "" {
		token := creds[u.Token]
		if token == "" {
			return FetchedFile{}, refusedFetch("the source's credentials have no %s", u.Token)
		}
		header.Set("Authorization", "Bearer "+token)
	}
	status, data, err := get(ctx, u.Client, link, header, URLDownloadLimit)
	if err != nil {
		return FetchedFile{}, err
	}
	if err := downloadStatus(status); err != nil {
		return FetchedFile{}, err
	}
	return FetchedFile{Data: data}, nil
}

func downloadStatus(status int) error {
	switch {
	case status == http.StatusOK:
		return nil
	case status == http.StatusTooManyRequests || status >= 500:
		return fmt.Errorf("file download answered %d", status)
	}
	return refusedFetch("the file download answered %d", status)
}

// get reads at most limit bytes of url; more is ErrFileTooLarge. A network failure is an error a retry may not repeat.
func get(ctx context.Context, client *http.Client, link string, header http.Header, limit int64) (int, []byte, error) {
	ctx, cancel := context.WithTimeout(ctx, fetchTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, link, nil)
	if err != nil {
		return 0, nil, refusedFetch("the file's URL is not valid")
	}
	for k, v := range header {
		req.Header[k] = v
	}
	resp, err := client.Do(req)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return 0, nil, fmt.Errorf("network: fetching an event file: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.ContentLength > limit {
		return 0, nil, ErrFileTooLarge
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return 0, nil, fmt.Errorf("network: reading an event file: %w", err)
	}
	if int64(len(data)) > limit {
		return 0, nil, ErrFileTooLarge
	}
	return resp.StatusCode, data, nil
}

// fileRef is an attachment's lazy reference: the fetch of its source type and the file object.
type fileRef struct {
	Fetch string         `json:"fetch"`
	Item  map[string]any `json:"item"`
}

// FilesLine is the task text of a message that carried files and no text.
func FilesLine(attachments []domain.Attachment) string {
	names := make([]string, 0, len(attachments))
	for _, a := range attachments {
		names = append(names, firstOf(oneLine(a.Name), "file"))
	}
	switch {
	case len(names) == 1 && names[0] == "file":
		return "(file)"
	case len(names) == 1:
		return "(file: " + names[0] + ")"
	}
	return "(files: " + strings.Join(names, ", ") + ")"
}

func megabytes(n int64) string { return fmt.Sprintf("%.1f MB", float64(n)/(1<<20)) }

// eventFiles brings the files of e into its workspace's files under events/<stream>/<event>/, once
// (a retry finds them there), and answers them as the attachments of the task it starts. A file
// that cannot come is a note for the task instead; an error is a failure a retry may not repeat.
func (s *Service) eventFiles(ctx context.Context, ws scope.Workspace, e domain.Event) ([]runsapi.TaskAttachment, []string, error) {
	if len(e.Attachments) == 0 {
		return nil, nil, nil
	}
	if s.d.Blob == nil {
		return nil, nil, errors.New("event files need the artifacts bucket, which is not wired")
	}
	store, err := kblob.ForWorkspace(s.d.Blob, e.WorkspaceID)
	if err != nil {
		return nil, nil, err
	}
	var out []runsapi.TaskAttachment
	var notes []string
	var creds map[string]string
	sourceName := "its source"
	for i, a := range e.Attachments {
		if a.Stored {
			if a.SHA256 == nil || a.Size == nil {
				notes = append(notes, fmt.Sprintf("The file %s was not attached: it was stored without its digest.", oneLine(a.Name)))
				continue
			}
			out = append(out, runsapi.TaskAttachment{Key: a.Ref, Name: safeName(a.Name), SHA256: *a.SHA256, Size: *a.Size, ContentType: contentTypeOf(a.Mime, a.Name)})
			continue
		}
		var ref fileRef
		if err := json.Unmarshal([]byte(a.Ref), &ref); err != nil || ref.Fetch == "" {
			notes = append(notes, fmt.Sprintf("The file %s was not attached: the event's reference to it cannot be read.", oneLine(a.Name)))
			continue
		}
		fetcher, ok := s.fetchers()[ref.Fetch]
		if !ok {
			notes = append(notes, fmt.Sprintf("The file %s was not attached: files of this source (%s) cannot be fetched.", oneLine(a.Name), ref.Fetch))
			continue
		}
		key := eventFilePath(e.StreamID, e.ID, fmt.Sprintf("%d-%s", i, safeName(a.Name)))
		if info, err := store.Stat(ctx, key); err == nil && info.SHA256 != "" {
			name := firstOf(info.Metadata["filename"], safeName(a.Name))
			out = append(out, runsapi.TaskAttachment{Key: key, Name: name, SHA256: info.SHA256, Size: info.Size, ContentType: firstOf(info.ContentType, contentTypeOf(a.Mime, name))})
			continue
		} else if err != nil && !errors.Is(err, kblob.ErrNotFound) {
			return nil, nil, err
		}
		if creds == nil {
			if creds, sourceName, err = s.eventCredentials(ctx, ws, e); err != nil {
				return nil, nil, err
			}
		}
		tooLarge := func(size string) string {
			return fmt.Sprintf("The file %s%s was not attached: %s files over %s cannot be fetched. "+
				"Tell the sender, and ask for a smaller file.", oneLine(a.Name), size, sourceName, megabytes(fetcher.Limit()))
		}
		if a.Size != nil && *a.Size > fetcher.Limit() {
			notes = append(notes, tooLarge(" ("+megabytes(*a.Size)+")"))
			continue
		}
		f, err := fetcher.Fetch(ctx, creds, ref.Item)
		var refused *fetchRefused
		switch {
		case errors.Is(err, ErrFileTooLarge):
			notes = append(notes, tooLarge(""))
			continue
		case errors.As(err, &refused):
			s.log.WarnContext(ctx, "An event file could not be fetched", "event_id", e.ID, "fetch", ref.Fetch, "error", err.Error())
			notes = append(notes, fmt.Sprintf("The file %s was not attached: %s.", oneLine(a.Name), refused.msg))
			continue
		case err != nil:
			return nil, nil, err
		}
		name := safeName(a.Name)
		if (a.Name == "" || a.Name == "file") && f.Name != "" {
			name = safeName(f.Name)
		}
		ct := contentTypeOf(a.Mime, name)
		if a.Mime == nil && f.ContentType != "" && f.ContentType != "application/octet-stream" {
			ct = f.ContentType
		}
		sum := sha256.Sum256(f.Data)
		digest := hex.EncodeToString(sum[:])
		if err := store.Put(ctx, key, bytesReader(f.Data), int64(len(f.Data)), kblob.PutOptions{
			ContentType: ct, Metadata: map[string]string{"sha256": digest, "filename": name}, SHA256: digest,
		}); err != nil {
			return nil, nil, err
		}
		out = append(out, runsapi.TaskAttachment{Key: key, Name: name, SHA256: digest, Size: int64(len(f.Data)), ContentType: ct})
	}
	return out, notes, nil
}

func contentTypeOf(declared *string, name string) string {
	if declared != nil && *declared != "" {
		return *declared
	}
	if ct := mime.TypeByExtension(strings.ToLower(path.Ext(name))); ct != "" {
		return ct
	}
	return "application/octet-stream"
}

// eventCredentials are the credentials of the source that brought e, and its type's name.
func (s *Service) eventCredentials(ctx context.Context, ws scope.Workspace, e domain.Event) (map[string]string, string, error) {
	if e.SourceID == nil {
		return map[string]string{}, "its source", nil
	}
	src, ok, err := s.sourceOf(ctx, ws, e)
	if err != nil {
		return nil, "", err
	}
	if !ok || src.SourceType == nil {
		return map[string]string{}, "its source", nil
	}
	name := *src.SourceType
	if entry, found, err := s.SourceTypeEntry(ctx, name); err != nil {
		return nil, "", err
	} else if found && entry.Name != "" {
		name = entry.Name
	}
	key := ""
	if src.CredentialKey != nil {
		key = *src.CredentialKey
	}
	creds, err := s.SourceCredentials(ctx, ws, src.CreatedBy, *src.SourceType, key)
	return creds, name, err
}
