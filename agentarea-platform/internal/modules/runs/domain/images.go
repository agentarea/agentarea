package domain

import (
	"fmt"
	"strings"
)

// MaxImagesPerModelCall and MaxPDFPagesPerModelCall: what tools returned is
// re-sent on every turn and costs tokens on every turn, so only the newest go.
const (
	MaxImagesPerModelCall   = 8
	MaxPDFPagesPerModelCall = 20
)

// PDFMimeType marks an attachment sent as a file rather than an image.
const PDFMimeType = "application/pdf"

// ContentPart is a part of a multi-part user message: text, an image by data
// URL, or a file (a PDF) by data URL.
type ContentPart struct {
	Type     string
	Text     string
	ImageURL string
	FileData string
	Filename string
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

func isPDF(ref ImageRef) bool { return ref.MimeType == PDFMimeType }

func kindOf(ref ImageRef) string {
	if isPDF(ref) {
		return "file"
	}
	return "image"
}

// ImageLimits are what the model's provider takes: one image's bytes and
// longer edge in pixels (0 is unstated), and whether it reads a PDF file.
type ImageLimits struct {
	MaxBytes, MaxEdge int
	PDF               bool
}

// Refusal is why ref is not shown to the model, "" when it fits.
func (l ImageLimits) Refusal(ref ImageRef) string {
	const fix = "; make a smaller copy or crop the part you need in the shell, then read_file that"
	switch {
	case isPDF(ref):
		if !l.PDF {
			return "this model's provider does not read PDFs; render the pages you need to PNG with pdftoppm in the shell and read_file those"
		}
	case l.MaxBytes > 0 && ref.Size > int64(l.MaxBytes):
		return fmt.Sprintf("%s is over the %s this model takes in one image%s", megabytes(ref.Size), megabytes(int64(l.MaxBytes)), fix)
	case l.MaxEdge > 0 && max(ref.Width, ref.Height) > l.MaxEdge:
		return fmt.Sprintf("%dx%d px is over the %d px edge this model takes%s", ref.Width, ref.Height, l.MaxEdge, fix)
	}
	return ""
}

func megabytes(n int64) string { return fmt.Sprintf("%.1f MB", float64(n)/(1<<20)) }

// ImagesToAttach are the ids of what tool messages returned that goes to the
// model, newest first within the budget: limit images and
// MaxPDFPagesPerModelCall PDF pages, each only if the model takes it.
func ImagesToAttach(messages []ChatMessage, limit int, fits ImageLimits) []string {
	var refs []ImageRef
	for _, m := range messages {
		if m.Role == "tool" {
			refs = append(refs, m.Attachments...)
		}
	}
	var ids []string
	images, pages := 0, 0
	for i := len(refs) - 1; i >= 0; i-- {
		ref := refs[i]
		if fits.Refusal(ref) != "" {
			continue
		}
		if isPDF(ref) {
			if pages+ref.Pages > MaxPDFPagesPerModelCall {
				continue
			}
			pages += ref.Pages
		} else {
			if images >= limit {
				continue
			}
			images++
		}
		ids = append([]string{ref.ID}, ids...)
	}
	return ids
}

// AttachToolImages is the conversation as the model receives it: the images
// and PDFs in dataURLs (nil for one that could not be read) go in a user
// message right after the tool results; one left out or unseen is named in its
// tool message, one over fits with what to do instead.
func AttachToolImages(messages []ChatMessage, dataURLs map[string]*string, vision bool, fits ImageLimits) []ModelMessage {
	type shownFiles struct {
		msg   ModelMessage
		parts []ContentPart
	}
	var out []ModelMessage
	var shown []shownFiles
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
			what := "Images"
			for _, p := range s.parts {
				if p.Type == "file" {
					what = "Files"
				}
			}
			parts = append(parts, ContentPart{Type: "text", Text: fmt.Sprintf("%s returned by %s (call %s):", what, name, s.msg.ToolCallID)})
			parts = append(parts, s.parts...)
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
		var parts []ContentPart
		var notes []string
		for _, ref := range m.Attachments {
			url, known := dataURLs[ref.ID]
			kind := kindOf(ref)
			switch {
			case !vision:
				notes = append(notes, fmt.Sprintf("[%s %s not shown: this model does not read images]", kind, ref.ID))
			case fits.Refusal(ref) != "":
				notes = append(notes, fmt.Sprintf("[%s %s not shown: %s]", kind, ref.ID, fits.Refusal(ref)))
			case !known:
				notes = append(notes, fmt.Sprintf("[%s %s from an earlier step is no longer attached]", kind, ref.ID))
			case url == nil:
				notes = append(notes, fmt.Sprintf("[%s %s could not be loaded]", kind, ref.ID))
			case isPDF(ref):
				parts = append(parts, ContentPart{Type: "file", FileData: *url, Filename: ref.ID + ".pdf"})
			default:
				parts = append(parts, ContentPart{Type: "image_url", ImageURL: *url})
			}
		}
		if len(notes) > 0 {
			msg.Content = strings.Join(append([]string{msg.Content}, notes...), "\n")
		}
		out = append(out, msg)
		if len(parts) > 0 {
			shown = append(shown, shownFiles{msg: msg, parts: parts})
		}
	}
	flush()
	return out
}
