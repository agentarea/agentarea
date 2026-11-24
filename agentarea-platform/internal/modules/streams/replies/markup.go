package replies

import (
	"fmt"
	"strings"
)

// Event is a task event as a sender sees it (the delivery-side payload).
type Event struct {
	Type      string
	ID        string
	TaskID    string
	Timestamp string
	Data      map[string]any
}

// Markup is how a chat renders bold, italic and quotes, which emoji it reads, and how text is
// escaped (markup.py MarkupFlavor).
type Markup struct {
	Bold, Italic [2]string
	Quote        string
	Emojis       map[string]string
	Escape       func(string) string
}

func colonEmojis() map[string]string {
	return map[string]string{
		"check": ":white_check_mark:", "cross": ":x:", "stop": ":no_entry_sign:", "question": ":question:",
		"hourglass": ":hourglass_flowing_sand:", "wrench": ":wrench:", "robot": ":robot_face:", "info": ":information_source:",
	}
}

func unicodeEmojis() map[string]string {
	return map[string]string{
		"check": "✅", "cross": "❌", "stop": "⛔", "question": "❓",
		"hourglass": "⏳", "wrench": "\U0001f527", "robot": "\U0001f916", "info": "ℹ️",
	}
}

func markdownV2Escape(text string) string {
	const special = "_*[]()~`>#+-=|{}.!\\"
	var b strings.Builder
	for _, r := range text {
		if strings.ContainsRune(special, r) {
			b.WriteByte('\\')
		}
		b.WriteRune(r)
	}
	return b.String()
}

// MarkupNamed is the flavour a reply block's markup names.
func MarkupNamed(name string) (Markup, error) {
	switch name {
	case "slack":
		return Markup{Bold: [2]string{"*", "*"}, Italic: [2]string{"_", "_"}, Quote: ">", Emojis: colonEmojis()}, nil
	case "discord":
		return Markup{Bold: [2]string{"**", "**"}, Italic: [2]string{"*", "*"}, Quote: "> ", Emojis: unicodeEmojis()}, nil
	case "telegram":
		return Markup{Bold: [2]string{"*", "*"}, Italic: [2]string{"_", "_"}, Quote: ">", Emojis: unicodeEmojis(), Escape: markdownV2Escape}, nil
	case "plain":
		return Markup{Bold: [2]string{"", ""}, Italic: [2]string{"", ""}, Quote: "> ", Emojis: unicodeEmojis()}, nil
	}
	return Markup{}, fatalf("unknown reply markup %q", name)
}

func (m Markup) esc(s string) string {
	if m.Escape == nil {
		return s
	}
	return m.Escape(s)
}

// FormatEvent is format_event: one task event as one chat line.
func FormatEvent(m Markup, e Event, presentation string) string {
	b0, b1, i0, i1, em := m.Bold[0], m.Bold[1], m.Italic[0], m.Italic[1], m.Emojis
	d := e.Data
	switch CanonicalType(e.Type) {
	case "task.completed":
		return m.esc(pyStr(firstTruthy(d, "final_response", "result"), ""))
	case "task.failed":
		return fmt.Sprintf("%s %sFailed%s — %s", em["cross"], b0, b1, m.esc(pyStr(get(d, "error"), "Unknown error")))
	case "task.cancelled":
		return em["stop"] + " " + m.esc("Task was cancelled.")
	case "approval.requested":
		return fmt.Sprintf("%s %sNeeds your input:%s\n%s%s", em["question"], b0, b1, m.Quote, m.esc(pyStr(get(d, "question"), "Approval needed")))
	case "approval.decided":
		switch d["approved"] {
		case true:
			return em["check"] + " " + m.esc("Approved, continuing...")
		case false:
			reason := ""
			if c := d["comment"]; truthy(c) {
				reason = " — " + m.esc(pyStr(c, ""))
			}
			return fmt.Sprintf("%s %sDenied%s%s", em["stop"], b0, b1, reason)
		}
		return em["info"] + " " + m.esc("Approval resolved.")
	}
	if presentation == Concise {
		switch CanonicalType(e.Type) {
		case "task.started", "command.received":
			return em["hourglass"] + " " + m.esc("Working on it...")
		case "tool.call":
			return fmt.Sprintf("%s %s%s%s%s", em["wrench"], m.esc("Using "), i0, m.esc(pyStr(get(d, "tool_name"), "tool")), i1+m.esc("..."))
		case "delegation.started", "delegation.completed":
			action := "Received from"
			switch {
			case CanonicalType(e.Type) == "delegation.completed":
			case d["remote"] == true:
				action = "Asking"
			default:
				action = "Delegating to"
			}
			name := pyStr(firstTruthy(d, "target_agent_name", "agent_name", "tool_name"), "sub-agent")
			return fmt.Sprintf("%s %s %s%s%s", em["robot"], action, i0, m.esc(name), i1)
		}
	}
	return em["info"] + " " + m.esc(e.Type)
}

// Limited is limited: message cut to limit characters, saying so in the flavour's markup. A cut
// never leaves a lone escape character at its end, which would make the whole text unparseable.
func Limited(m Markup, message string, limit *int) string {
	r := []rune(message)
	if limit == nil || len(r) <= *limit {
		return message
	}
	suffix := "\n\n" + m.Italic[0] + m.esc("(truncated)") + m.Italic[1]
	keep := max(*limit-len([]rune(suffix)), 0)
	cut := r[:keep]
	if m.Escape != nil {
		n := 0
		for i := len(cut) - 1; i >= 0 && cut[i] == '\\'; i-- {
			n++
		}
		if n%2 == 1 {
			cut = cut[:len(cut)-1]
		}
	}
	return string(cut) + suffix
}

// StripMarkup is the text without lightweight markdown and escape markers, for a plain resend.
func StripMarkup(text string) string {
	for _, marker := range []string{"\\", "*", "_", "`"} {
		text = strings.ReplaceAll(text, marker, "")
	}
	return text
}

func get(d map[string]any, k string) any { return d[k] }

// pyStr is str(d.get(k, def)), with a null value read as missing: a reply never says "None".
func pyStr(v any, def string) string {
	switch x := v.(type) {
	case nil:
		return def
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	}
	return fmt.Sprint(v)
}

func firstTruthy(d map[string]any, keys ...string) any {
	for _, k := range keys {
		if v := d[k]; truthy(v) {
			return v
		}
	}
	return nil
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	case float64:
		return x != 0
	case int:
		return x != 0
	case int64:
		return x != 0
	case map[string]any:
		return len(x) > 0
	case []any:
		return len(x) > 0
	}
	return true
}
