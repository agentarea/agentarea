package domain

import (
	"fmt"
	"strings"
)

// MaxImagesPerModelCall: images re-sent on every turn cost tokens on every turn, so only the newest go.
const MaxImagesPerModelCall = 8

// ContentPart is a part of a multi-part user message: text, or an image by data URL.
type ContentPart struct {
	Type     string
	Text     string
	ImageURL string
}

// ModelMessage is a message as the provider receives it; Parts replaces Content when set.
type ModelMessage struct {
	Role       string
	Content    string
	Parts      []ContentPart
	ToolCalls  []ToolCall
	ToolCallID string
	Name       string
}

// StoredImageID is the id a tool output's image is stored under.
func StoredImageID(outputID string, index int) string {
	return fmt.Sprintf("%s_image_%d", outputID, index)
}

// ImagesToAttach are the ids of the newest limit images tool messages reference.
func ImagesToAttach(messages []ChatMessage, limit int) []string {
	var ids []string
	for _, m := range messages {
		if m.Role != "tool" {
			continue
		}
		for _, ref := range m.Attachments {
			ids = append(ids, ref.ID)
		}
	}
	if limit <= 0 {
		return nil
	}
	if len(ids) > limit {
		ids = ids[len(ids)-limit:]
	}
	return ids
}

// AttachToolImages is the conversation as the model receives it: the images
// in dataURLs (nil for one that could not be read) go in a user message right
// after the tool results; one left out or unseen is named in its tool message.
func AttachToolImages(messages []ChatMessage, dataURLs map[string]*string, vision bool) []ModelMessage {
	type shownImages struct {
		msg  ModelMessage
		urls []string
	}
	var out []ModelMessage
	var shown []shownImages
	flush := func() {
		if len(shown) == 0 {
			return
		}
		var parts []ContentPart
		for _, s := range shown {
			name := s.msg.Name
			if name == "" {
				name = "the tool"
			}
			parts = append(parts, ContentPart{Type: "text", Text: fmt.Sprintf("Images returned by %s (call %s):", name, s.msg.ToolCallID)})
			for _, u := range s.urls {
				parts = append(parts, ContentPart{Type: "image_url", ImageURL: u})
			}
		}
		out = append(out, ModelMessage{Role: "user", Parts: parts})
		shown = nil
	}
	for _, m := range messages {
		msg := ModelMessage{Role: m.Role, Content: m.Content, ToolCalls: m.ToolCalls, ToolCallID: m.ToolCallID, Name: m.Name}
		if m.Role != "tool" {
			flush()
			out = append(out, msg)
			continue
		}
		var urls, notes []string
		for _, ref := range m.Attachments {
			url, known := dataURLs[ref.ID]
			switch {
			case !vision:
				notes = append(notes, fmt.Sprintf("[image %s not shown: this model does not read images]", ref.ID))
			case !known:
				notes = append(notes, fmt.Sprintf("[image %s from an earlier step is no longer attached]", ref.ID))
			case url == nil:
				notes = append(notes, fmt.Sprintf("[image %s could not be loaded]", ref.ID))
			default:
				urls = append(urls, *url)
			}
		}
		if len(notes) > 0 {
			msg.Content = strings.Join(append([]string{msg.Content}, notes...), "\n")
		}
		out = append(out, msg)
		if len(urls) > 0 {
			shown = append(shown, shownImages{msg: msg, urls: urls})
		}
	}
	flush()
	return out
}
