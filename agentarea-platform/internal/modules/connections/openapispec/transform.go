package openapispec

import (
	"bytes"
	"encoding/base64"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"mime/quotedprintable"
	"net/mail"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

var pathStep = regexp.MustCompile(`^(?:\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\])`)

// JSONPath is tool_cost.json_path: the value at path ($, .key and [n]
// steps) in doc; false when absent.
func JSONPath(doc any, path string) (any, bool) {
	if !strings.HasPrefix(path, "$") {
		return nil, false
	}
	rest, node := path[1:], doc
	for rest != "" {
		m := pathStep.FindStringSubmatch(rest)
		if m == nil {
			return nil, false
		}
		if m[1] != "" {
			o, ok := asObject(node)
			if !ok {
				return nil, false
			}
			v, ok := o.Get(m[1])
			if !ok {
				return nil, false
			}
			node = v
		} else {
			list, ok := node.([]any)
			i, err := strconv.Atoi(m[2])
			if !ok || err != nil || i >= len(list) {
				return nil, false
			}
			node = list[i]
		}
		rest = rest[len(m[0]):]
	}
	return node, true
}

// TransformError is a request or response transform that does not fit:
// RequestTransformError or ResponseTransformError.
type TransformError struct{ Msg string }

func (e *TransformError) Error() string { return e.Msg }

func transformErr(format string, args ...any) error {
	return &TransformError{Msg: fmt.Sprintf(format, args...)}
}

func addressHeaders() []struct{ field, header string } {
	return []struct{ field, header string }{
		{"from", "From"}, {"to", "To"}, {"cc", "Cc"}, {"bcc", "Bcc"}, {"reply_to", "Reply-To"},
	}
}

func mailFields() map[string]bool {
	return map[string]bool{
		"from": true, "to": true, "cc": true, "bcc": true, "reply_to": true,
		"subject": true, "text": true, "html": true, "in_reply_to": true, "references": true,
	}
}

// CheckRequestTransform is validate_request_transform.
func CheckRequestTransform(steps any) error {
	list, ok := steps.([]any)
	if !ok {
		return transformErr("x-agentarea-request-transform must be a list")
	}
	for _, step := range list {
		o, ok := asObject(step)
		if !ok || get(o, "build", nil) != "rfc822" {
			return transformErr("unknown request transform step %s", repr(step))
		}
		if s, isStr := get(o, "into", nil).(string); !isStr || s == "" {
			return transformErr("a request transform step needs into: <field>, got %s", repr(step))
		}
	}
	return nil
}

// ApplyRequestTransform is apply_request_transform: the body with every step applied.
func ApplyRequestTransform(steps []any, body any) (any, error) {
	if err := CheckRequestTransform(steps); err != nil {
		return nil, err
	}
	for _, step := range steps {
		o, ok := asObject(body)
		if !ok {
			return nil, transformErr("the request body must be an object")
		}
		fields := map[string]any{}
		var kept wirejson.Object
		for _, m := range o {
			if mailFields()[m.Key] {
				fields[m.Key] = m.Value
			} else {
				kept = append(kept, m)
			}
		}
		built, err := buildRFC822(fields)
		if err != nil {
			return nil, err
		}
		so, _ := asObject(step)
		into, _ := get(so, "into", nil).(string)
		kept.Set(into, built)
		body = kept
	}
	return body, nil
}

func addresses(v any, field string) (string, error) {
	var items []any
	switch t := v.(type) {
	case string:
		items = []any{t}
	case []any:
		items = t
	default:
		return "", transformErr("%s must be an address or a list of addresses", field)
	}
	var out []string
	for _, it := range items {
		s, ok := it.(string)
		if !ok {
			return "", transformErr("%s must be an address or a list of addresses", field)
		}
		if s = strings.TrimSpace(s); s != "" {
			out = append(out, s)
		}
	}
	return strings.Join(out, ", "), nil
}

func text(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return repr(v)
}

func headerValue(s string) (string, error) {
	if strings.ContainsAny(s, "\r\n") {
		return "", transformErr("the message cannot be built: header values may not contain linefeed or carriage return characters")
	}
	return mime.QEncoding.Encode("utf-8", s), nil
}

func qpBody(s string) []byte {
	var b bytes.Buffer
	w := quotedprintable.NewWriter(&b)
	_, _ = w.Write([]byte(strings.ReplaceAll(s, "\r\n", "\n")))
	_ = w.Close()
	return b.Bytes()
}

func buildRFC822(fields map[string]any) (string, error) {
	if !truthy(fields["to"]) && !truthy(fields["cc"]) && !truthy(fields["bcc"]) {
		return "", transformErr("a message needs at least one of to, cc or bcc")
	}
	txt, html := fields["text"], fields["html"]
	if !truthy(txt) && !truthy(html) {
		return "", transformErr("a message needs text or html")
	}
	var head bytes.Buffer
	add := func(name, value string) error {
		v, err := headerValue(value)
		if err != nil {
			return err
		}
		fmt.Fprintf(&head, "%s: %s\r\n", name, v)
		return nil
	}
	for _, h := range addressHeaders() {
		if truthy(fields[h.field]) {
			v, err := addresses(fields[h.field], h.field)
			if err != nil {
				return "", err
			}
			if err := add(h.header, v); err != nil {
				return "", err
			}
		}
	}
	if truthy(fields["subject"]) {
		if err := add("Subject", text(fields["subject"])); err != nil {
			return "", err
		}
	}
	if truthy(fields["in_reply_to"]) {
		if err := add("In-Reply-To", text(fields["in_reply_to"])); err != nil {
			return "", err
		}
	}
	if refs := fields["references"]; truthy(refs) {
		list, ok := refs.([]any)
		if !ok {
			list = []any{refs}
		}
		parts := make([]string, len(list))
		for i, r := range list {
			parts[i] = text(r)
		}
		if err := add("References", strings.Join(parts, " ")); err != nil {
			return "", err
		}
	}
	head.WriteString("MIME-Version: 1.0\r\n")
	var msg bytes.Buffer
	msg.Write(head.Bytes())
	single := func(subtype string, body string) {
		fmt.Fprintf(&msg, "Content-Type: text/%s; charset=\"utf-8\"\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n", subtype)
		msg.Write(qpBody(body))
	}
	switch {
	case truthy(txt) && truthy(html):
		var parts bytes.Buffer
		mw := multipart.NewWriter(&parts)
		fmt.Fprintf(&msg, "Content-Type: multipart/alternative; boundary=%q\r\n\r\n", mw.Boundary())
		for _, p := range []struct{ subtype, body string }{{"plain", text(txt)}, {"html", text(html)}} {
			w, _ := mw.CreatePart(map[string][]string{
				"Content-Type":              {fmt.Sprintf("text/%s; charset=\"utf-8\"", p.subtype)},
				"Content-Transfer-Encoding": {"quoted-printable"},
			})
			_, _ = w.Write(qpBody(p.body))
		}
		_ = mw.Close()
		msg.Write(parts.Bytes())
	case truthy(txt):
		single("plain", text(txt))
	default:
		single("html", text(html))
	}
	return base64.URLEncoding.EncodeToString(msg.Bytes()), nil
}

const maxXMLBytes = 8 << 20

var base64url = regexp.MustCompile(`^[A-Za-z0-9_-]*={0,2}$`)

func decodeBase64(v any) (any, error) {
	s, ok := v.(string)
	if !ok {
		return nil, transformErr("base64 input must be text")
	}
	raw, err := base64.StdEncoding.Strict().DecodeString(s)
	if err != nil {
		return nil, transformErr("invalid base64: %v", err)
	}
	if !utf8.Valid(raw) {
		return nil, transformErr("invalid base64: the bytes are not UTF-8")
	}
	return string(raw), nil
}

func decodeBase64URL(v any) (any, error) {
	s, ok := v.(string)
	if !ok {
		return nil, transformErr("base64url input must be text")
	}
	if !base64url.MatchString(s) {
		return nil, transformErr("invalid base64url: unexpected characters")
	}
	s = strings.TrimRight(s, "=")
	raw, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return nil, transformErr("invalid base64url: %v", err)
	}
	return string(raw), nil
}

type xmlNode struct {
	tag      string
	attrs    wirejson.Object
	children []*xmlNode
	text     strings.Builder
}

func parseXML(v any) (any, error) {
	s, ok := v.(string)
	if !ok {
		return nil, transformErr("xml input must be text")
	}
	if len(s) > maxXMLBytes {
		return nil, transformErr("xml document is too large")
	}
	if strings.Contains(s, "<!DOCTYPE") || strings.Contains(s, "<!ENTITY") {
		return nil, transformErr("xml documents with a DOCTYPE or ENTITY are refused")
	}
	dec := xml.NewDecoder(strings.NewReader(s))
	dec.Strict = true
	var stack []*xmlNode
	var root *xmlNode
	for {
		tok, err := dec.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, transformErr("invalid xml: %v", err)
		}
		switch t := tok.(type) {
		case xml.StartElement:
			if root != nil && len(stack) == 0 {
				return nil, transformErr("invalid xml: junk after document element")
			}
			n := &xmlNode{tag: xmlName(t.Name)}
			for _, a := range t.Attr {
				if a.Name.Space == "xmlns" || (a.Name.Space == "" && a.Name.Local == "xmlns") {
					continue
				}
				n.attrs = append(n.attrs, wirejson.Member{Key: "@" + xmlName(a.Name), Value: a.Value})
			}
			if len(stack) > 0 {
				parent := stack[len(stack)-1]
				parent.children = append(parent.children, n)
			} else {
				root = n
			}
			stack = append(stack, n)
		case xml.EndElement:
			stack = stack[:len(stack)-1]
		case xml.CharData:
			if len(stack) > 0 {
				top := stack[len(stack)-1]
				if len(top.children) == 0 {
					top.text.Write(t)
				}
			}
		}
	}
	if root == nil {
		return nil, transformErr("invalid xml: no element found")
	}
	return wirejson.Object{{Key: root.tag, Value: xmlElement(root)}}, nil
}

func xmlName(n xml.Name) string {
	if n.Space == "" {
		return n.Local
	}
	return "{" + n.Space + "}" + n.Local
}

func xmlElement(n *xmlNode) any {
	out := append(wirejson.Object{}, n.attrs...)
	for _, c := range n.children {
		v := xmlElement(c)
		if existing, ok := out.Get(c.tag); ok {
			if list, isList := existing.([]any); isList {
				out.Set(c.tag, append(list, v))
			} else {
				out.Set(c.tag, []any{existing, v})
			}
		} else {
			out = append(out, wirejson.Member{Key: c.tag, Value: v})
		}
	}
	txt := strings.TrimSpace(n.text.String())
	if len(out) == 0 {
		return txt
	}
	if txt != "" {
		out = append(out, wirejson.Member{Key: "#text", Value: txt})
	}
	return out
}

func rfc822Headers() []struct{ field, header string } {
	return []struct{ field, header string }{
		{"from", "From"}, {"to", "To"}, {"cc", "Cc"}, {"reply_to", "Reply-To"}, {"subject", "Subject"},
		{"date", "Date"}, {"message_id", "Message-ID"}, {"in_reply_to", "In-Reply-To"}, {"references", "References"},
	}
}

type mailPart struct {
	header mail.Header
	body   []byte
}

func partText(h mail.Header, body []byte) string {
	if strings.EqualFold(h.Get("Content-Transfer-Encoding"), "quoted-printable") {
		if b, err := io.ReadAll(quotedprintable.NewReader(bytes.NewReader(body))); err == nil {
			body = b
		}
	} else if strings.EqualFold(h.Get("Content-Transfer-Encoding"), "base64") {
		if b, err := base64.StdEncoding.DecodeString(strings.Join(strings.Fields(string(body)), "")); err == nil {
			body = b
		}
	}
	return strings.ToValidUTF8(string(body), "�")
}

func partSize(h mail.Header, body []byte) int {
	switch strings.ToLower(h.Get("Content-Transfer-Encoding")) {
	case "base64":
		if b, err := base64.StdEncoding.DecodeString(strings.Join(strings.Fields(string(body)), "")); err == nil {
			return len(b)
		}
	case "quoted-printable":
		if b, err := io.ReadAll(quotedprintable.NewReader(bytes.NewReader(body))); err == nil {
			return len(b)
		}
	}
	return len(body)
}

// leaves walks a message's parts depth first.
func leaves(h mail.Header, body []byte, depth int, out *[]mailPart) {
	media, params, err := mime.ParseMediaType(h.Get("Content-Type"))
	if err == nil && strings.HasPrefix(media, "multipart/") && depth < 16 {
		r := multipart.NewReader(bytes.NewReader(body), params["boundary"])
		for {
			p, err := r.NextRawPart()
			if err != nil {
				break
			}
			b, _ := io.ReadAll(p)
			leaves(mail.Header(p.Header), b, depth+1, out)
		}
		return
	}
	*out = append(*out, mailPart{header: h, body: body})
}

func contentType(h mail.Header) string {
	media, _, err := mime.ParseMediaType(h.Get("Content-Type"))
	if err != nil || media == "" {
		return "text/plain"
	}
	return media
}

func filename(h mail.Header) any {
	if _, params, err := mime.ParseMediaType(h.Get("Content-Disposition")); err == nil && params["filename"] != "" {
		return params["filename"]
	}
	if _, params, err := mime.ParseMediaType(h.Get("Content-Type")); err == nil && params["name"] != "" {
		return params["name"]
	}
	return nil
}

func isAttachment(h mail.Header) bool {
	d, _, _ := mime.ParseMediaType(h.Get("Content-Disposition"))
	return strings.EqualFold(d, "attachment") || (filename(h) != nil && !strings.EqualFold(d, "inline"))
}

func parseRFC822(v any) (any, error) {
	s, ok := v.(string)
	if !ok {
		return nil, transformErr("rfc822 input must be text")
	}
	m, err := mail.ReadMessage(strings.NewReader(s))
	if err != nil {
		return nil, transformErr("rfc822 input is not a message")
	}
	body, _ := io.ReadAll(m.Body)
	out := wirejson.Object{}
	dec := new(mime.WordDecoder)
	for _, h := range rfc822Headers() {
		if vals, ok := m.Header[h.header]; ok && len(vals) > 0 {
			v := vals[0]
			if d, err := dec.DecodeHeader(v); err == nil {
				v = d
			}
			out = append(out, wirejson.Member{Key: h.field, Value: v})
		}
	}
	var parts []mailPart
	leaves(m.Header, body, 0, &parts)
	var plain, html *mailPart
	var attachments []any
	for i := range parts {
		p := &parts[i]
		ct := contentType(p.header)
		if isAttachment(p.header) {
			attachments = append(attachments, wirejson.Object{
				{Key: "filename", Value: filename(p.header)},
				{Key: "content_type", Value: ct},
				{Key: "size", Value: partSize(p.header, p.body)},
			})
			continue
		}
		switch {
		case ct == "text/plain" && plain == nil:
			plain = p
		case ct == "text/html" && html == nil:
			html = p
		}
	}
	if plain != nil {
		out = append(out, wirejson.Member{Key: "text", Value: partText(plain.header, plain.body)})
	} else {
		out = append(out, wirejson.Member{Key: "text", Value: ""})
		if html != nil {
			out = append(out, wirejson.Member{Key: "html", Value: partText(html.header, html.body)})
		}
	}
	if attachments == nil {
		attachments = []any{}
	}
	out = append(out, wirejson.Member{Key: "attachments", Value: attachments})
	return out, nil
}

func responseSteps() map[[2]string]func(any) (any, error) {
	return map[[2]string]func(any) (any, error){
		{"decode", "base64"}:    decodeBase64,
		{"decode", "base64url"}: decodeBase64URL,
		{"parse", "xml"}:        parseXML,
		{"parse", "rfc822"}:     parseRFC822,
	}
}

func setAt(doc any, path string, v any) error {
	i := strings.LastIndex(path, ".")
	if i <= 0 || strings.Contains(path[i+1:], "[") {
		return transformErr("cannot replace %s: it must end in .field", path)
	}
	parent, ok := JSONPath(doc, path[:i])
	if !ok {
		return transformErr("the response carries no %s", path[:i])
	}
	o, ok := parent.(wirejson.Object)
	if !ok {
		if m, isMap := parent.(map[string]any); isMap {
			m[path[i+1:]] = v
			return nil
		}
		return transformErr("cannot replace %s: its parent is not an object", path)
	}
	key := path[i+1:]
	for j := range o {
		if o[j].Key == key {
			o[j].Value = v
			return nil
		}
	}
	return transformErr("cannot replace %s: its parent is fixed", path)
}

// ApplyResponseTransform is apply_response_transform: the body with every step applied.
func ApplyResponseTransform(steps []any, body any) (any, error) {
	for _, step := range steps {
		o, ok := asObject(step)
		at, isStr := get(o, "at", nil).(string)
		if !ok || !isStr {
			return nil, transformErr("a transform step needs at: <path>, got %s", repr(step))
		}
		var kinds [][2]string
		for _, kind := range []string{"decode", "parse"} {
			if v, ok := o.Get(kind); ok {
				s, _ := v.(string)
				kinds = append(kinds, [2]string{kind, s})
			}
		}
		if len(kinds) != 1 || responseSteps()[kinds[0]] == nil {
			return nil, transformErr("unknown transform step %s", repr(step))
		}
		current, ok := JSONPath(body, at)
		if !ok {
			return nil, transformErr("the response carries no %s", at)
		}
		v, err := responseSteps()[kinds[0]](current)
		if err != nil {
			return nil, err
		}
		if at == "$" {
			body = v
		} else if err := setAt(body, at, v); err != nil {
			return nil, err
		}
	}
	return body, nil
}
