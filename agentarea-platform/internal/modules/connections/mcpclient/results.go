package mcpclient

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
)

func decodeNumbers(raw []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	return dec.Decode(v)
}

// SerializeTool is serialize_mcp_tool: the stored shape of a listed tool
// (name, description, inputSchema, title, the hints the server set, and of
// _meta only the MCP Apps ui, with the flat ui/resourceUri folded in).
func SerializeTool(t map[string]any) map[string]any {
	out := map[string]any{"name": t["name"]}
	desc, _ := t["description"].(string)
	out["description"] = desc
	schema, ok := t["inputSchema"].(map[string]any)
	if !ok || schema == nil {
		schema = map[string]any{}
	}
	out["inputSchema"] = schema
	if title, ok := t["title"].(string); ok && title != "" {
		out["title"] = title
	}
	if ann, ok := t["annotations"].(map[string]any); ok {
		kept := map[string]any{}
		for k, v := range ann {
			if v != nil {
				kept[k] = v
			}
		}
		if len(kept) > 0 {
			out["annotations"] = kept
		}
	}
	if meta, ok := t["_meta"].(map[string]any); ok {
		ui := map[string]any{}
		if m, ok := meta["ui"].(map[string]any); ok {
			for k, v := range m {
				ui[k] = v
			}
		}
		if _, has := ui["resourceUri"]; !has {
			if v, ok := meta["ui/resourceUri"]; ok {
				ui["resourceUri"] = v
			}
		}
		if len(ui) > 0 {
			out["_meta"] = map[string]any{"ui": ui}
		}
	}
	return out
}

// Image is an image a tool result carried, decoded from the base64 the server sent.
type Image struct {
	MimeType string
	Data     []byte
}

// Image limits of split_tool_content.
const (
	MaxToolImageBytes = 5 * 1024 * 1024
	MaxToolImages     = 8
)

func supportedImageType(mime string) bool {
	switch mime {
	case "image/png", "image/jpeg", "image/gif", "image/webp":
		return true
	}
	return false
}

// SplitContent is split_tool_content: the result's text, and its images.
// Every image is named in the text where it appeared.
func SplitContent(blocks []map[string]any) (string, []Image) {
	var parts []string
	var images []Image
	image := func(mime, encoded, uri string) {
		data, decodeErr := base64.StdEncoding.DecodeString(encoded)
		switch {
		case !supportedImageType(mime):
			parts = append(parts, fmt.Sprintf("[image omitted: %s is not a supported image type]", mime))
		case decodeErr != nil:
			parts = append(parts, fmt.Sprintf("[image omitted: %s data is not base64]", mime))
		case len(data) > MaxToolImageBytes:
			parts = append(parts, fmt.Sprintf("[image omitted: %s is larger than %d bytes]", mime, MaxToolImageBytes))
		case len(images) >= MaxToolImages:
			parts = append(parts, fmt.Sprintf("[image omitted: more than %d images in one result]", MaxToolImages))
		default:
			images = append(images, Image{MimeType: mime, Data: data})
			label := mime
			if uri != "" {
				label = mime + " " + uri
			}
			parts = append(parts, fmt.Sprintf("[image %d: %s]", len(images), label))
		}
	}
	str := func(m map[string]any, k string) string { s, _ := m[k].(string); return s }
	for _, b := range blocks {
		switch str(b, "type") {
		case "text":
			parts = append(parts, str(b, "text"))
		case "image":
			image(str(b, "mimeType"), str(b, "data"), "")
		case "resource":
			r, _ := b["resource"].(map[string]any)
			mime := str(r, "mimeType")
			blob, hasBlob := r["blob"].(string)
			switch {
			case hasBlob && len(mime) >= 6 && mime[:6] == "image/":
				image(mime, blob, str(r, "uri"))
			case hasBlob:
				if mime == "" {
					mime = "binary"
				}
				parts = append(parts, fmt.Sprintf("[resource %s: %s, not shown]", str(r, "uri"), mime))
			default:
				parts = append(parts, fmt.Sprintf("[resource %s]\n%s", str(r, "uri"), str(r, "text")))
			}
		case "resource_link":
			parts = append(parts, fmt.Sprintf("[resource link %s]", str(b, "uri")))
		default:
			raw, _ := json.Marshal(b)
			parts = append(parts, string(raw))
		}
	}
	out := ""
	for i, p := range parts {
		if i > 0 {
			out += "\n"
		}
		out += p
	}
	return out, images
}
