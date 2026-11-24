package replies

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// TelegramUploadLimit is the largest file a bot sends (multipart upload); TelegramPhotoLimit the
// largest it sends as a photo.
const (
	TelegramUploadLimit = 50 << 20
	TelegramPhotoLimit  = 10 << 20

	telegramFilesPrefix = "tg:files:"
	telegramFilesTTL    = 7 * 24 * time.Hour
	telegramUploadWait  = 2 * time.Minute
	maxFilesPerTurn     = 10
)

// FileRefused is the Bot API refusing a file: what it said, for the chat. TooLarge is a file
// over what a bot uploads (413, or over TelegramUploadLimit before sending).
type FileRefused struct {
	Description string
	TooLarge    bool
}

func (e *FileRefused) Error() string { return "telegram refused the file: " + e.Description }

// uploadMethod is the Bot API method and its file field for a file of contentType and size: a
// video Telegram plays, a photo it shows, else a document.
func uploadMethod(contentType string, size int64) (string, string) {
	ct, _, _ := mime.ParseMediaType(contentType)
	switch {
	case ct == "video/mp4":
		return "sendVideo", "video"
	case (ct == "image/jpeg" || ct == "image/png" || ct == "image/webp") && size <= TelegramPhotoLimit:
		return "sendPhoto", "photo"
	}
	return "sendDocument", "document"
}

// File sends data to chatID as a file of its own: a video, a photo or a document by its type.
// A video or photo Telegram refuses goes again as a document. A refusal is a *FileRefused; any
// other error may not repeat.
func (t TelegramLive) File(ctx context.Context, token string, chatID any, name, contentType string, data []byte) error {
	if contentType == "" {
		contentType = mime.TypeByExtension(strings.ToLower(path.Ext(name)))
	}
	method, field := uploadMethod(contentType, int64(len(data)))
	status, body, err := t.upload(ctx, token, method, field, chatID, name, data)
	if err == nil && status == http.StatusBadRequest && method != "sendDocument" {
		status, body, err = t.upload(ctx, token, "sendDocument", "document", chatID, name, data)
	}
	if err != nil {
		return err
	}
	if status == http.StatusTooManyRequests || status >= 500 {
		return fmt.Errorf("telegram %s answered %d", method, status)
	}
	var answer struct {
		OK          bool   `json:"ok"`
		Description string `json:"description"`
	}
	_ = json.Unmarshal(body, &answer)
	if !answer.OK || status != http.StatusOK {
		if answer.Description == "" {
			answer.Description = fmt.Sprintf("HTTP %d", status)
		}
		return &FileRefused{Description: answer.Description, TooLarge: status == http.StatusRequestEntityTooLarge}
	}
	return nil
}

func (t TelegramLive) upload(ctx context.Context, token, method, field string, chatID any, name string, data []byte) (int, []byte, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	_ = w.WriteField("chat_id", fmt.Sprint(chatID))
	if method == "sendVideo" {
		_ = w.WriteField("supports_streaming", "true")
	}
	part, err := w.CreateFormFile(field, name)
	if err != nil {
		return 0, nil, err
	}
	if _, err := part.Write(data); err != nil {
		return 0, nil, err
	}
	if err := w.Close(); err != nil {
		return 0, nil, err
	}
	base := t.API
	if base == "" {
		base = TelegramAPI
	}
	ctx, cancel := context.WithTimeout(ctx, telegramUploadWait)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/bot"+token+"/"+method, &buf)
	if err != nil {
		return 0, nil, fatalf("telegram %s request: %v", method, err)
	}
	req.Header.Set("Content-Type", w.FormDataContentType())
	resp, err := t.Client.Do(req)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return 0, nil, fmt.Errorf("network: telegram %s: %w", method, err)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxAnswer))
	_ = resp.Body.Close()
	if err != nil {
		return 0, nil, fmt.Errorf("network: telegram %s answer: %w", method, err)
	}
	return resp.StatusCode, body, nil
}

// sendOutputs sends the chat the files the task published that it has not sent yet, each once
// (by path and digest). A file Telegram refuses or one too large to send is a short note in the
// chat instead; a failure that may not repeat is returned, and the files sent so far stay sent.
func (t TelegramLive) sendOutputs(ctx context.Context, s Send, token string, chatID any) error {
	if t.Files == nil {
		return nil
	}
	files, err := t.Files.Artifacts(ctx, s.Workspace.ID(), s.Event.TaskID)
	var notes []string
	switch {
	case errors.Is(err, sandboxapi.ErrTaskFilesNotConfigured):
		notes = append(notes, "The task's files could not be sent: "+err.Error())
	case err != nil:
		return fmt.Errorf("files of task %s: %w", s.Event.TaskID, err)
	}
	key := telegramFilesPrefix + s.Event.TaskID
	sent := 0
	for _, f := range files {
		mark := f.Path + "@" + f.SHA256
		if done, err := t.Redis.SIsMember(ctx, key, mark).Result(); err != nil {
			return fmt.Errorf("sent files of task %s: %w", s.Event.TaskID, err)
		} else if done {
			continue
		}
		name := f.Name
		if name == "" {
			name = path.Base(f.Path)
		}
		if sent == maxFilesPerTurn {
			notes = append(notes, fmt.Sprintf("More files are in the task; the chat gets the first %d.", maxFilesPerTurn))
			break
		}
		tooLarge := func() error {
			page, err := t.taskPage(ctx, s)
			if err != nil {
				return err
			}
			if page == "" {
				notes = append(notes, fmt.Sprintf("%s is %.1f MB; a Telegram bot sends files up to 50 MB.", name, float64(f.Size)/(1<<20)))
				return nil
			}
			notes = append(notes, LinkedFile(name, f.Size, TaskFileURL(page, f.Path)))
			return nil
		}
		if f.Size > TelegramUploadLimit {
			if err := tooLarge(); err != nil {
				return err
			}
		} else {
			err := t.sendArtifact(ctx, s, token, chatID, f, name)
			var refused *FileRefused
			switch {
			case errors.As(err, &refused) && refused.TooLarge:
				if err := tooLarge(); err != nil {
					return err
				}
			case errors.As(err, &refused):
				notes = append(notes, fmt.Sprintf("Could not send %s: %s", name, refused.Description))
			case err != nil:
				return err
			}
			sent++
		}
		if err := t.Redis.SAdd(ctx, key, mark).Err(); err != nil {
			return err
		}
		if err := t.Redis.Expire(ctx, key, telegramFilesTTL).Err(); err != nil {
			return err
		}
	}
	if len(notes) == 0 {
		return nil
	}
	_, _, err = t.Message(ctx, token, chatID, strings.Join(notes, "\n"))
	var refused *TelegramRefused
	if errors.As(err, &refused) {
		return nil
	}
	return err
}

func (t TelegramLive) sendArtifact(ctx context.Context, s Send, token string, chatID any, f sandboxapi.TaskArtifact, name string) error {
	d, err := t.Files.Artifact(ctx, s.Workspace.ID(), s.Event.TaskID, f.ID)
	if err != nil {
		return fmt.Errorf("file %s of task %s: %w", f.Path, s.Event.TaskID, err)
	}
	defer func() { _ = d.Body.Close() }()
	data, err := io.ReadAll(io.LimitReader(d.Body, TelegramUploadLimit+1))
	if err != nil {
		return fmt.Errorf("file %s of task %s: %w", f.Path, s.Event.TaskID, err)
	}
	if len(data) > TelegramUploadLimit {
		return &FileRefused{Description: "larger than the 50 MB a Telegram bot sends", TooLarge: true}
	}
	ct := f.ContentType
	if ct == "" || ct == "application/octet-stream" {
		ct = mime.TypeByExtension(strings.ToLower(path.Ext(name)))
	}
	return t.File(ctx, token, chatID, name, ct, data)
}
