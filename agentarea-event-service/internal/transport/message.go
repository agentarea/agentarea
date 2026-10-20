package transport

import (
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"mime"
	"strings"
	"time"

	"github.com/emersion/go-message"
	_ "github.com/emersion/go-message/charset" // decodes the charsets mail is written in
	"github.com/emersion/go-message/mail"
)

// A part bigger than this keeps its name, type and size, not its bytes: the
// broker is not a file store.
const maxAttachmentBytes = 10 << 20

// ParseMessage reads an RFC 5322 message into the imap item shape:
// {message_id, from, reply_to, to, cc, subject, date, in_reply_to,
// references[], text, html, attachments[{name, mime, size, content_base64}]}.
func ParseMessage(raw []byte) (map[string]any, error) {
	reader, err := mail.CreateReader(bytes.NewReader(raw))
	if err != nil && !message.IsUnknownCharset(err) {
		return nil, fmt.Errorf("read message: %w", err)
	}
	defer reader.Close()

	header := reader.Header
	item := map[string]any{
		"message_id":  "",
		"from":        addresses(header, "From"),
		"reply_to":    addresses(header, "Reply-To"),
		"to":          addresses(header, "To"),
		"cc":          addresses(header, "Cc"),
		"subject":     "",
		"date":        "",
		"in_reply_to": "",
		"references":  []any{},
		"text":        "",
		"html":        "",
		"attachments": []any{},
	}
	if id, err := header.MessageID(); err == nil {
		item["message_id"] = id
	}
	if subject, err := header.Subject(); err == nil {
		item["subject"] = subject
	} else {
		item["subject"] = header.Get("Subject")
	}
	if date, err := header.Date(); err == nil && !date.IsZero() {
		item["date"] = date.UTC().Format(time.RFC3339)
	}
	if ids, err := header.MsgIDList("In-Reply-To"); err == nil && len(ids) > 0 {
		item["in_reply_to"] = ids[0]
	}
	if ids, err := header.MsgIDList("References"); err == nil {
		refs := make([]any, 0, len(ids))
		for _, id := range ids {
			refs = append(refs, id)
		}
		item["references"] = refs
	}

	var text, html strings.Builder
	var attachments []any
	for {
		part, err := reader.NextPart()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil && !message.IsUnknownCharset(err) {
			return nil, fmt.Errorf("read message part: %w", err)
		}
		if part == nil {
			break
		}
		switch h := part.Header.(type) {
		case *mail.InlineHeader:
			contentType, _, _ := h.ContentType()
			body, err := io.ReadAll(part.Body)
			if err != nil {
				return nil, fmt.Errorf("read message part: %w", err)
			}
			switch contentType {
			case "text/plain", "":
				text.Write(body)
			case "text/html":
				html.Write(body)
			default:
				attachments = append(attachments, attachment(inlineName(h), contentType, body))
			}
		case *mail.AttachmentHeader:
			contentType, _, _ := h.ContentType()
			name, _ := h.Filename()
			body, err := io.ReadAll(part.Body)
			if err != nil {
				return nil, fmt.Errorf("read attachment: %w", err)
			}
			attachments = append(attachments, attachment(name, contentType, body))
		}
	}
	item["text"] = text.String()
	item["html"] = html.String()
	if attachments != nil {
		item["attachments"] = attachments
	}
	return item, nil
}

func attachment(name, contentType string, body []byte) map[string]any {
	a := map[string]any{"name": name, "mime": contentType, "size": len(body), "content_base64": ""}
	if len(body) <= maxAttachmentBytes {
		a["content_base64"] = base64.StdEncoding.EncodeToString(body)
	}
	return a
}

func inlineName(h *mail.InlineHeader) string {
	if _, params, err := h.ContentType(); err == nil && params["name"] != "" {
		return params["name"]
	}
	if _, params, err := mime.ParseMediaType(h.Get("Content-Disposition")); err == nil {
		return params["filename"]
	}
	return ""
}

func addresses(header mail.Header, key string) string {
	list, err := header.AddressList(key)
	if err != nil {
		return header.Get(key)
	}
	parts := make([]string, 0, len(list))
	for _, a := range list {
		if a.Name == "" {
			parts = append(parts, a.Address)
			continue
		}
		parts = append(parts, a.String())
	}
	return strings.Join(parts, ", ")
}
