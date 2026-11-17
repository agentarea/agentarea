package domain

import (
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

// Context store limits (workflows/constants.py).
const (
	OutputOffloadChars     = 8000
	ReadOutputMaxChars     = 16000
	OutputSummaryHeadChars = 500
	OutputSummaryTailChars = 200
	HistorySearchMaxResult = 20
	TokensPerMessage       = 4
	SkillContextShare      = 0.1
	SkillFilesListed       = 50
	SeenURLsLimit          = 5000
	skillContentTag        = "<skill_content"
)

// OutputKey, HistoryChunkKey, HistoryPrefix and ImageKey are where a task's
// offloaded context lives in object storage (context_store.py).
func OutputKey(workspaceID, taskID, outputID string) string {
	return fmt.Sprintf("tasks/%s/%s/outputs/%s.json", workspaceID, taskID, outputID)
}

func HistoryChunkKey(workspaceID, taskID string, index int) string {
	return fmt.Sprintf("tasks/%s/%s/history/chunk_%d.json", workspaceID, taskID, index)
}

func HistoryPrefix(workspaceID, taskID string) string {
	return fmt.Sprintf("tasks/%s/%s/history/", workspaceID, taskID)
}

func ImageKey(workspaceID, taskID, imageID string) string {
	return fmt.Sprintf("tasks/%s/%s/images/%s", workspaceID, taskID, imageID)
}

func runeLen(s string) int { return len([]rune(s)) }

func runeHead(s string, n int) string {
	r := []rune(s)
	if n >= len(r) {
		return s
	}
	return string(r[:n])
}

func runeTail(s string, n int) string {
	r := []rune(s)
	if n >= len(r) {
		return s
	}
	return string(r[len(r)-n:])
}

// lineMatcher is the grep of read_tool_output: a case-insensitive regex, or a
// literal substring when the pattern is not one.
func lineMatcher(pattern string) func(string) bool {
	re, err := regexp.Compile("(?i)" + pattern)
	if err != nil {
		return func(s string) bool { return strings.Contains(s, pattern) }
	}
	return re.MatchString
}

// FilterOutput is read_output: grep, then head or tail lines, capped at ReadOutputMaxChars.
func FilterOutput(content, grep string, head, tail *int) string {
	lines := strings.Split(content, "\n")
	if grep != "" {
		match := lineMatcher(grep)
		kept := lines[:0:0]
		for _, l := range lines {
			if match(l) {
				kept = append(kept, l)
			}
		}
		lines = kept
	}
	switch {
	case head != nil && *head > 0:
		if *head < len(lines) {
			lines = lines[:*head]
		}
	case tail != nil && *tail > 0:
		if *tail < len(lines) {
			lines = lines[len(lines)-*tail:]
		}
	}
	result := strings.Join(lines, "\n")
	if runeLen(result) > ReadOutputMaxChars {
		result = runeHead(result, ReadOutputMaxChars) + fmt.Sprintf("\n... [truncated at %d chars]", ReadOutputMaxChars)
	}
	return result
}

// HistoryMessage is one message of a stored history chunk.
type HistoryMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
	Name    string `json:"name,omitempty"`
}

// HistoryMatches is search_history over the messages of the chunks, in order;
// it returns the formatted lines and whether the result limit was reached.
func HistoryMatches(messages []HistoryMessage, grep, toolName string, found []string) []string {
	var match func(string) bool
	if grep != "" {
		match = lineMatcher(grep)
	}
	for _, m := range messages {
		if len(found) >= HistorySearchMaxResult {
			break
		}
		if toolName != "" && m.Name != toolName {
			continue
		}
		if match != nil && !match(m.Content) {
			continue
		}
		role := m.Role
		if role == "" {
			role = "unknown"
		}
		suffix := ""
		if m.Name != "" {
			suffix = " (" + m.Name + ")"
		}
		found = append(found, fmt.Sprintf("[%s%s]: %s", role, suffix, runeHead(m.Content, 500)))
	}
	return found
}

// HistorySearchResult formats what HistoryMatches found.
func HistorySearchResult(found []string) string {
	if len(found) == 0 {
		return "No matching messages found in history."
	}
	out := strings.Join(found, "\n---\n")
	if runeLen(out) > ReadOutputMaxChars {
		out = runeHead(out, ReadOutputMaxChars) + "\n... [truncated]"
	}
	return out
}

func thousands(n int) string {
	s := fmt.Sprint(n)
	if n < 0 {
		return "-" + thousands(-n)
	}
	var b strings.Builder
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	return b.String()
}

// OutputSummary is build_output_summary: what the model reads of an offloaded output.
func OutputSummary(content, outputID string) string {
	total := runeLen(content)
	lines := strings.Count(content, "\n") + 1
	s := fmt.Sprintf("[Output stored as %s — %s chars, %d lines]\n", outputID, thousands(total), lines)
	s += fmt.Sprintf("Preview:\n%s\n", runeHead(content, OutputSummaryHeadChars))
	if total > OutputSummaryHeadChars+OutputSummaryTailChars {
		s += fmt.Sprintf("...\n%s\n", runeTail(content, OutputSummaryTailChars))
	}
	return s + fmt.Sprintf("\nUse read_tool_output(\"%s\") for full content, or read_tool_output(\"%s\", grep=\"pattern\") to search.", outputID, outputID)
}

// EstimateTokens approximates a text's tokens at four characters each.
func EstimateTokens(text string) int { return (runeLen(text) + 3) / 4 }

// ChatMessage is a log entry as a chat model reads it.
type ChatMessage struct {
	Role        string
	Content     string
	ToolCalls   []ToolCall
	ToolCallID  string
	Name        string
	Attachments []ImageRef
}

// AsMessage is the entry as the model reads it; a compaction is a user message.
func (e Entry) AsMessage() ChatMessage {
	role := e.Role
	if e.Kind == KindCompaction {
		role = "user"
	}
	return ChatMessage{Role: role, Content: e.Content, ToolCalls: e.ToolCalls, ToolCallID: e.ToolCallID, Name: e.Name, Attachments: e.Attachments}
}

// MessagesTokens estimates the tokens of a message list.
func MessagesTokens(messages []ChatMessage) int {
	n := 0
	for _, m := range messages {
		n += EstimateTokens(m.Content) + TokensPerMessage
		for _, c := range m.ToolCalls {
			n += EstimateTokens(c.Name) + EstimateTokens(c.Arguments)
		}
	}
	return n
}

// CompactionInput is compaction_input: the messages a compaction summarizes,
// the skill texts it carries verbatim, and the entries it replaces.
func CompactionInput(window []Entry) ([]ChatMessage, []string, []Entry) {
	var previous *Entry
	for i := range window {
		if window[i].Kind == KindCompaction {
			previous = &window[i]
			break
		}
	}
	var skills []string
	var summarize []ChatMessage
	if previous != nil {
		if carried, ok := previous.Meta["skills"].([]any); ok {
			for _, s := range carried {
				if text, ok := s.(string); ok {
					skills = append(skills, text)
				}
			}
		}
		summarize = append(summarize, ChatMessage{Role: "user", Content: previous.Content})
	}
	var replaced []Entry
	for _, e := range window {
		if e.Kind == KindMessage && e.Role != "system" {
			replaced = append(replaced, e)
		}
	}
	for _, e := range replaced {
		m := e.AsMessage()
		if strings.Contains(e.Content, skillContentTag) {
			if !containsString(skills, e.Content) {
				skills = append(skills, e.Content)
			}
			m.Content = skillStandIn(e.Content)
		}
		summarize = append(summarize, m)
	}
	return summarize, skills, replaced
}

func containsString(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func skillStandIn(content string) string {
	name := ""
	if m := regexp.MustCompile(`<skill_content name="([^"]+)"`).FindStringSubmatch(content); m != nil {
		name = " '" + m[1] + "'"
	}
	return fmt.Sprintf("[Skill%s activated. It stays active: its full instructions are kept verbatim right after the summary.]", name)
}

// CompactionSystemPrompt is the summarizer's system message.
// CompactionSummaryHeader opens a compaction row.
const CompactionSummaryHeader = "[Previous conversation summary]"

const CompactionSystemPrompt = "You are a conversation summarizer. Create concise, factual summaries that preserve all important information for continuing the task."

// CompactionPrompt is the request to summarize messages into the sections a run continues from.
func CompactionPrompt(messages []ChatMessage) string {
	var text strings.Builder
	for _, m := range messages {
		role := m.Role
		if role == "" {
			role = "unknown"
		}
		content := m.Content
		if len(m.ToolCalls) > 0 {
			names := make([]string, 0, len(m.ToolCalls))
			for _, c := range m.ToolCalls {
				n := c.Name
				if n == "" {
					n = "?"
				}
				names = append(names, n)
			}
			content += " [Called tools: " + strings.Join(names, ", ") + "]"
		}
		if m.Name != "" {
			role = "tool(" + m.Name + ")"
		}
		fmt.Fprintf(&text, "[%s]: %s\n", role, content)
	}
	return "Summarize the conversation below. The summary replaces it: the work continues " +
		"from the summary alone, so keep everything that work needs. Write these " +
		"sections, in this order, each under its own heading:\n" +
		"1. Original request and intent: what was asked for, and why.\n" +
		"2. User messages: every message the user sent, in order, quoted or closely " +
		"paraphrased.\n" +
		"3. Key facts and data: what the tools returned that the work depends on " +
		"(names, ids, numbers, paths, URLs, decisions).\n" +
		"4. Errors and how they were handled.\n" +
		"5. Still open: questions, requirements or problems not yet resolved.\n" +
		"6. Work in progress: what was being done when the conversation was cut, and " +
		"how far it got. Name every skill marked activated as active; it need not be " +
		"activated again.\n" +
		"7. Next step: the next action to take.\n\n" +
		"Be concise but complete; use bullet points for facts.\n\n" +
		"Conversation to summarize:\n" + text.String()
}

func filesNote(directory string, paths []string) string {
	shown := paths
	if len(shown) > SkillFilesListed {
		shown = shown[:SkillFilesListed]
	}
	lines := make([]string, 0, len(shown)+1)
	for _, p := range shown {
		lines = append(lines, "- "+p)
	}
	if len(paths) > len(shown) {
		lines = append(lines, fmt.Sprintf("- ... and %d more", len(paths)-len(shown)))
	}
	return fmt.Sprintf("This skill's files are in %s/ in your sandbox:\n%s\nRun them with the shell tool, e.g. bash(\"python %s/<script>\").", directory, strings.Join(lines, "\n"), directory)
}

// SkillEntry is skill_entry: the activated skill's log entry within
// maxTokens, and whether it points at its SKILL.md instead of quoting it.
func SkillEntry(name, body string, maxTokens int, directory string, paths []string, pointer string) (string, bool) {
	notes := []string{""}
	if directory != "" {
		notes = []string{filesNote(directory, paths), fmt.Sprintf("This skill's files are in %s/ in your sandbox.", directory), ""}
	}
	withNote := func(content, note string) string {
		if note == "" {
			return content
		}
		return content + "\n\n" + note
	}
	for _, note := range notes {
		if c := withNote(WrapSkillContent(name, body, nil), note); EstimateTokens(c) <= maxTokens {
			return c, false
		}
	}
	lead := fmt.Sprintf("This skill's SKILL.md is %s characters (about %s tokens), more than the %s tokens its instructions may take in this run, so it is not shown here in full. %s",
		thousands(runeLen(body)), thousands(EstimateTokens(body)), thousands(maxTokens), pointer)
	for _, note := range notes {
		for _, preview := range []int{2000, 1000, 400, 0} {
			opening := ""
			if preview > 0 {
				opening = fmt.Sprintf("\n\nIt opens with:\n%s\n[...]", runeHead(body, preview))
			}
			if c := withNote(WrapSkillContent(name, lead+opening, nil), note); EstimateTokens(c) <= maxTokens {
				return c, true
			}
		}
	}
	return WrapSkillContent(name, runeHead(lead, max(0, maxTokens*2)), nil), true
}

// ComparableURL is a URL reduced to what identifies the page: host, port,
// path and query (comparable_url); false when it is not an http(s) URL.
func ComparableURL(raw string) (string, bool) {
	u, err := url.Parse(strings.TrimRight(strings.TrimSpace(raw), ".,;:!?"))
	if err != nil {
		return "", false
	}
	scheme := strings.ToLower(u.Scheme)
	host := strings.ToLower(u.Hostname())
	if (scheme != "http" && scheme != "https") || host == "" {
		return "", false
	}
	port := u.Port()
	if port != "" {
		n, err := strconv.Atoi(port)
		if err != nil || n < 0 || n > 65535 {
			return "", false
		}
		if (scheme == "http" && n == 80) || (scheme == "https" && n == 443) {
			port = ""
		} else {
			port = strconv.Itoa(n)
		}
	}
	netloc := host
	if port != "" {
		netloc += ":" + port
	}
	path, err := url.PathUnescape(u.EscapedPath())
	if err != nil {
		path = u.Path
	}
	out := netloc + strings.TrimRight(path, "/")
	if q, err := url.QueryUnescape(strings.ReplaceAll(u.RawQuery, "+", "%2B")); err == nil && q != "" {
		out += "?" + q
	} else if err != nil && u.RawQuery != "" {
		out += "?" + u.RawQuery
	}
	return out, true
}

// ExternalURLs are the comparable links in messages the model did not write
// itself, in order of first appearance (external_urls).
func ExternalURLs(entries []Entry) []string {
	re := regexp.MustCompile(`(?i)https?://[^\s"'<>` + "`" + `\\()\[\]{}]+`)
	seen := map[string]bool{}
	var out []string
	for _, e := range entries {
		if e.Role == "assistant" {
			continue
		}
		for _, candidate := range re.FindAllString(e.Content, -1) {
			if u, ok := ComparableURL(candidate); ok && !seen[u] {
				seen[u] = true
				out = append(out, u)
			}
		}
	}
	return out
}
