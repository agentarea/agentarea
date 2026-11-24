package domain

import (
	"regexp"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// The answer check (answer_check.py): a deterministic look at a final answer
// for what a person should not have to read, and the one rewrite call.

// pyWS is Python's Unicode \s; pyNonWS its complement.
const (
	pyWS    = `[\s\v\p{Z}\x{85}\x{1c}-\x{1f}]`
	pyNonWS = `[^\s\v\p{Z}\x{85}\x{1c}-\x{1f}]`
)

var (
	cjkRe        = regexp.MustCompile(`[\x{3040}-\x{30ff}\x{3400}-\x{4dbf}\x{4e00}-\x{9fff}\x{ac00}-\x{d7af}\x{f900}-\x{faff}]+`)
	stackRe      = regexp.MustCompile(`(?m)(?:^|` + pyWS + `)at` + pyWS + `+` + pyNonWS + `+` + pyWS + `+\(?/|node_modules/|Traceback \(most recent call last\)`)
	stackWordRe  = regexp.MustCompile(`TypeError|ReferenceError|SyntaxError|ENOENT`)
	errorColonRe = regexp.MustCompile(`Error:` + pyWS)
	jsonLikeRe   = regexp.MustCompile(`\{` + pyWS + `*"[A-Za-z_]+"` + pyWS + `*:`)
	identRe      = regexp.MustCompile(`^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$`)
	cyrillicRe   = regexp.MustCompile(`[\x{0400}-\x{04ff}]`)
	urlRe        = regexp.MustCompile(`https?://[^\s\v\p{Z}\x{85}\x{1c}-\x{1f})]+|/api/[^\s\v\p{Z}\x{85}\x{1c}-\x{1f})]+`)
	fenceRe      = regexp.MustCompile("```[\\s\\S]*?```")
	mdLinkRe     = regexp.MustCompile(`\]\([^)]*\)`)
	httpRe       = regexp.MustCompile(`https?://` + pyNonWS + `+`)
	apiPathRe    = regexp.MustCompile(`/api/` + pyNonWS + `+`)
	fileNameRe   = regexp.MustCompile(`(?i)([\p{L}\p{N}_.\- ]+\.(?:xlsx|xls|pdf|docx|csv|jpe?g|png))([^\p{L}\p{N}_]|$)`)
	answerRe     = regexp.MustCompile(`<answer>([\s\S]*?)</answer>`)
	changesRe    = regexp.MustCompile(`<changes>([\s\S]*?)</changes>`)
	spacesRe     = regexp.MustCompile(` {2,}`)
)

const leakSampleLength = 80

func allowedEnglish(word string) bool {
	switch word {
	case "xlsx", "docx", "html", "http", "https", "mailto":
		return true
	default:
		return false
	}
}

// Leak is one thing found in an answer: Kind is cjk, tool_name, identifier,
// stack_trace, json or english.
type Leak struct {
	Kind   string
	Sample string
}

// Rewrite is a usable rewrite and the model's account of it.
type Rewrite struct {
	Answer  string
	Changes string
}

// AnswerCheckConfig is the run's enabled answer check, or nil: a governance
// rule that sets answer_check wins over the agent's own setting, on or off.
func AnswerCheckConfig(policy api.Policy, agent *api.AnswerCheck) *api.AnswerCheck {
	config := agent
	if cs := policy.ContentSafety; cs != nil && cs.AnswerCheck != nil {
		config = cs.AnswerCheck
	}
	if config == nil || !config.Enabled {
		return nil
	}
	return config
}

// pyWord is Python's Unicode \w.
func pyWord(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r) }

func boundaryAt(s string, i int) bool {
	before, after := false, false
	if i > 0 {
		r, _ := utf8.DecodeLastRuneInString(s[:i])
		before = pyWord(r)
	}
	if i < len(s) {
		r, _ := utf8.DecodeRuneInString(s[i:])
		after = pyWord(r)
	}
	return before != after
}

// ProseOnly drops links, file names and code blocks: the person's data, not our wording.
func ProseOnly(text string) string {
	text = fenceRe.ReplaceAllString(text, " ")
	text = mdLinkRe.ReplaceAllString(text, "]")
	text = httpRe.ReplaceAllString(text, " ")
	text = apiPathRe.ReplaceAllString(text, " ")
	return fileNameRe.ReplaceAllString(text, " $2")
}

func mostlyCyrillic(text string) bool {
	letters := 0
	for _, r := range text {
		if pyWord(r) && r != '_' && !unicode.Is(unicode.Nd, r) {
			letters++
		}
	}
	return letters > 0 && len(cyrillicRe.FindAllStringIndex(text, -1))*2 >= letters
}

type match struct {
	at   int
	text string
}

func firstMatch(cands ...*match) *match {
	var best *match
	for _, c := range cands {
		if c != nil && (best == nil || c.at < best.at) {
			best = c
		}
	}
	return best
}

func reMatch(re *regexp.Regexp, s string) *match {
	loc := re.FindStringIndex(s)
	if loc == nil {
		return nil
	}
	return &match{at: loc[0], text: s[loc[0]:loc[1]]}
}

// boundedMatch is the first match of re that starts and ends on a word boundary.
func boundedMatch(re *regexp.Regexp, s string, endBoundary bool) *match {
	for _, loc := range re.FindAllStringIndex(s, -1) {
		if boundaryAt(s, loc[0]) && (!endBoundary || boundaryAt(s, loc[1])) {
			return &match{at: loc[0], text: s[loc[0]:loc[1]]}
		}
	}
	return nil
}

func stackMatch(s string) *match {
	return firstMatch(reMatch(stackRe, s), boundedMatch(stackWordRe, s, true), boundedMatch(errorColonRe, s, false))
}

// words are the maximal runs of word characters of s.
func words(s string) []match {
	var out []match
	start := -1
	for i, r := range s {
		switch {
		case pyWord(r) && start < 0:
			start = i
		case !pyWord(r) && start >= 0:
			out = append(out, match{at: start, text: s[start:i]})
			start = -1
		}
	}
	if start >= 0 {
		out = append(out, match{at: start, text: s[start:]})
	}
	return out
}

func identifierMatch(s string) *match {
	for _, w := range words(s) {
		if identRe.MatchString(w.text) {
			return &w
		}
	}
	return nil
}

func containsWord(s, name string) bool {
	for i := 0; i <= len(s)-len(name); {
		j := strings.Index(s[i:], name)
		if j < 0 {
			return false
		}
		at := i + j
		if boundaryAt(s, at) && boundaryAt(s, at+len(name)) {
			return true
		}
		_, size := utf8.DecodeRuneInString(s[at:])
		i = at + size
	}
	return false
}

// englishMatch is the first lowercase Latin word of four letters or more, not part of a path or a longer word.
func englishMatch(s string) *match {
	for i := 0; i < len(s); {
		if s[i] < 'a' || s[i] > 'z' {
			_, size := utf8.DecodeRuneInString(s[i:])
			i += size
			continue
		}
		j := i
		for j < len(s) && s[j] >= 'a' && s[j] <= 'z' {
			j++
		}
		prevOK := true
		if i > 0 {
			r, _ := utf8.DecodeLastRuneInString(s[:i])
			prevOK = !pyWord(r) && r != '.' && r != '/' && r != '-'
		}
		nextOK := true
		if j < len(s) {
			r, _ := utf8.DecodeRuneInString(s[j:])
			nextOK = !pyWord(r)
		}
		if prevOK && nextOK && j-i >= 4 && !allowedEnglish(s[i:j]) {
			return &match{at: i, text: s[i:j]}
		}
		i = j
	}
	return nil
}

func sample(text string) string {
	t := strings.TrimSpace(text)
	if utf8.RuneCountInString(t) > leakSampleLength {
		t = string([]rune(t)[:leakSampleLength])
	}
	return t
}

// FindLeaks is what in text a person should not have to read. The English
// word check runs only for language "ru" and an answer that is mostly Cyrillic.
func FindLeaks(text string, toolNames []string, language string) []Leak {
	prose := ProseOnly(text)
	var leaks []Leak
	add := func(kind string, m *match) {
		if m != nil {
			leaks = append(leaks, Leak{Kind: kind, Sample: sample(m.text)})
		}
	}
	if language != "zh" && language != "ja" && language != "ko" {
		add("cjk", reMatch(cjkRe, prose))
	}
	toolLeak := false
	for _, name := range toolNames {
		if name != "" && containsWord(prose, name) {
			leaks = append(leaks, Leak{Kind: "tool_name", Sample: sample(name)})
			toolLeak = true
			break
		}
	}
	add("stack_trace", stackMatch(prose))
	add("json", reMatch(jsonLikeRe, prose))
	if !toolLeak {
		add("identifier", identifierMatch(prose))
	}
	if language == "ru" && mostlyCyrillic(prose) {
		add("english", englishMatch(prose))
	}
	return leaks
}

// ToolNamesOf are the names a model could quote: each tool's name and, for MCP, its raw name.
func ToolNamesOf(tools []api.ToolDefinition) []string {
	var names []string
	for _, t := range tools {
		if t.Name == "" {
			continue
		}
		names = append(names, t.Name)
		if strings.HasPrefix(t.Name, "mcp__") {
			raw := t.Name[strings.LastIndex(t.Name, "__")+2:]
			if raw != "" && !slices.Contains(names, raw) {
				names = append(names, raw)
			}
		}
	}
	return names
}

const (
	rewriteSystemRU = "Ты редактор ответов ассистента. Перепиши ответ для человека:\n" +
		"- тот же смысл, все цифры, суммы, ссылки и названия файлов — дословно, " +
		"markdown-ссылки не трогай;\n" +
		"- только по-русски: переведи английские слова, убери иероглифы;\n" +
		"- убери названия инструментов, коды и ключи (snake_case), JSON, тексты ошибок " +
		"и стек-трейсы — скажи по-человечески, что произошло, если это важно;\n" +
		"- не добавляй нового и не сокращай по смыслу."
	rewriteSystem = "You edit an assistant's answer for the person reading it. Rewrite it:\n" +
		"- same meaning; every number, amount, link and file name verbatim; leave " +
		"markdown links as they are;\n" +
		"- in the answer's own language; remove characters from other scripts;\n" +
		"- remove tool names, codes and keys (snake_case), JSON, error texts and stack " +
		"traces; say plainly what happened if it matters;\n" +
		"- add nothing and drop nothing of substance."
	replyFormatRU = "\n\nВерни ровно два блока:\n" +
		"<changes>что ты исправил, по пункту в строке</changes>\n" +
		"<answer>\nисправленный ответ целиком\n</answer>\n" +
		"Внутри <answer> только сам ответ, как его прочтёт человек: без пометок, " +
		"без заголовков вроде «Ответ:» и без списка исправлений."
	replyFormat = "\n\nReturn exactly two blocks:\n" +
		"<changes>what you fixed, one item per line</changes>\n" +
		"<answer>\nthe whole corrected answer\n</answer>\n" +
		"Inside <answer> put only the answer as the person will read it: no notes, " +
		"no headings such as 'Answer:', no list of fixes."
)

// RewriteMessages are the one rewrite call's system and user texts.
func RewriteMessages(text string, leaks []Leak, language, instruction string) (system, user string) {
	sys, format := rewriteSystem, replyFormat
	if language == "ru" {
		sys, format = rewriteSystemRU, replyFormatRU
	}
	if instruction != "" {
		sys = instruction
	}
	found := make([]string, len(leaks))
	for i, l := range leaks {
		found[i] = "- " + l.Kind + " «" + l.Sample + "»"
	}
	return sys + format, "<problems>\n" + strings.Join(found, "\n") + "\n</problems>\n<answer>\n" + text + "\n</answer>"
}

// AcceptRewrite is the rewrite if usable: exactly one closed, non-empty
// <answer> block keeping every link of the original.
func AcceptRewrite(original, reply string, stripCJK bool) *Rewrite {
	answers := answerRe.FindAllStringSubmatch(reply, -1)
	if len(answers) != 1 {
		return nil
	}
	candidate := strings.TrimSpace(answers[0][1])
	if candidate == "" {
		return nil
	}
	for _, link := range urlRe.FindAllString(original, -1) {
		if !strings.Contains(candidate, link) {
			return nil
		}
	}
	changes := ""
	if m := changesRe.FindStringSubmatch(reply); m != nil {
		changes = strings.TrimSpace(m[1])
	}
	if stripCJK {
		candidate = StripUnreadable(candidate)
	}
	return &Rewrite{Answer: candidate, Changes: changes}
}

// StripUnreadable drops CJK characters, which the reader cannot read.
func StripUnreadable(text string) string {
	return spacesRe.ReplaceAllString(cjkRe.ReplaceAllString(text, ""), " ")
}
