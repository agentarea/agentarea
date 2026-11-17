package mcpserver

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	connectionsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

const (
	scoreExactName   = 100
	scoreNameToken   = 3
	scoreNamePrefix  = 2
	scoreDescription = 1
	confirmMessage   = "This tool is marked destructive. Ask the user to confirm, then call again with confirm=true."
)

var tokenSplit = regexp.MustCompile(`[^a-z0-9]+`)

func searchTokens(text string) map[string]bool {
	out := map[string]bool{}
	for _, t := range tokenSplit.Split(strings.ToLower(text), -1) {
		if t != "" {
			out[t] = true
		}
	}
	return out
}

// searchScore is _score: an exact name, name tokens, name prefixes of three
// or more characters, then description and title tokens.
func searchScore(query string, queryTokens map[string]bool, tool connectionsapi.ConnectorTool) int {
	nameTokens := searchTokens(tool.Name)
	descTokens := searchTokens(tool.Description + " " + tool.Title)
	score := 0
	if strings.EqualFold(strings.TrimSpace(query), tool.Name) {
		score = scoreExactName
	}
	for token := range queryTokens {
		switch {
		case nameTokens[token]:
			score += scoreNameToken
		case len(token) >= 3 && anyPrefixed(nameTokens, token):
			score += scoreNamePrefix
		case descTokens[token]:
			score += scoreDescription
		}
	}
	return score
}

func anyPrefixed(tokens map[string]bool, prefix string) bool {
	for t := range tokens {
		if strings.HasPrefix(t, prefix) {
			return true
		}
	}
	return false
}

func inputSchemaOrObject(s any) any {
	switch v := s.(type) {
	case nil:
		return map[string]any{"type": "object"}
	case map[string]any:
		if len(v) == 0 {
			return map[string]any{"type": "object"}
		}
	}
	return s
}

func nullableHint(h string) any {
	if h == "" {
		return nil
	}
	return h
}

// connectorCallError is the ToolError each refusal of a call reads as.
func connectorCallError(connector, tool string, err error) error {
	var ambiguous *connectionsapi.AmbiguousConnectorError
	var unknown *connectionsapi.UnknownToolError
	var failed *connectionsapi.ToolCallFailedError
	switch {
	case errors.Is(err, connectionsapi.ErrNoConnector):
		return &toolError{"No connector named " + domain.PyRepr(connector)}
	case errors.As(err, &ambiguous):
		return jsonToolError(
			"error", "Connector name "+domain.PyRepr(connector)+" is ambiguous; pass one of its ids",
			"connector_ids", ambiguous.IDs)
	case errors.As(err, &unknown):
		return jsonToolError(
			"error", unknown.Connector+" has no tool "+domain.PyRepr(tool),
			"suggestions", closeMatches(tool, unknown.Names, 5, 0.6))
	case errors.As(err, &failed):
		return &toolError{fmt.Sprintf("Calling %s on %s failed: %v", tool, failed.Connector, failed.Err)}
	}
	return err
}

// jsonToolError is a ToolError whose text is json.dumps of the object
// {k1: v1, k2: v2}, keys in that order.
func jsonToolError(k1 string, v1 any, k2 string, v2 any) error {
	var parts []string
	for _, kv := range [][2]any{{k1, v1}, {k2, v2}} {
		k, err := pyJSON(kv[0])
		if err != nil {
			return err
		}
		v, err := pyJSON(kv[1])
		if err != nil {
			return err
		}
		parts = append(parts, k+": "+v)
	}
	return &toolError{"{" + strings.Join(parts, ", ") + "}"}
}

// pyJSON is json.dumps' default form: ", " and ": " separators, non-ASCII escaped.
func pyJSON(v any) (string, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	raw := strings.TrimSuffix(buf.String(), "\n")
	var b strings.Builder
	inString, escaped := false, false
	for _, r := range raw {
		switch {
		case inString:
			switch {
			case escaped:
				escaped = false
			case r == '\\':
				escaped = true
			case r == '"':
				inString = false
			}
			if r > 0x7e {
				if r > 0xffff {
					r -= 0x10000
					fmt.Fprintf(&b, `\u%04x\u%04x`, 0xd800+(r>>10), 0xdc00+(r&0x3ff))
				} else {
					fmt.Fprintf(&b, `\u%04x`, r)
				}
				continue
			}
		case r == '"':
			inString = true
		case r == ',':
			b.WriteString(", ")
			continue
		case r == ':':
			b.WriteString(": ")
			continue
		}
		b.WriteRune(r)
	}
	return b.String(), nil
}

// connectorTools is tools/connector_tools_toolset.py.
func connectorTools(t connectionsapi.PlatformConnectorTools) map[string]toolDef {
	return map[string]toolDef{
		"search": {title: "Search connector tools", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Query     string  `json:"query"`
				Connector *string `json:"connector"`
				Limit     *int    `json:"limit"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 8
			if in.Limit != nil {
				limit = *in.Limit
			}
			if limit < 1 || limit > 50 {
				return nil, &toolError{fmt.Sprintf("limit must be between 1 and 50, got %d", limit)}
			}
			connectors, err := t.Searchable(ctx, c, in.Connector)
			if err != nil {
				return nil, err
			}
			queryTokens := searchTokens(in.Query)
			type ranked struct {
				score           int
				connector, tool string
				result          map[string]any
			}
			var matches []ranked
			for _, conn := range connectors {
				for _, tool := range conn.Tools {
					score := searchScore(in.Query, queryTokens, tool)
					if score <= 0 {
						continue
					}
					matches = append(matches, ranked{score, strings.ToLower(conn.Name), tool.Name, map[string]any{
						"connector_id": conn.ID, "connector": conn.Name, "tool": tool.Name,
						"description": tool.Description, "hint": nullableHint(tool.Hint),
						"inputSchema": inputSchemaOrObject(tool.InputSchema),
					}})
				}
			}
			sort.SliceStable(matches, func(i, j int) bool {
				a, b := matches[i], matches[j]
				if a.score != b.score {
					return a.score > b.score
				}
				if a.connector != b.connector {
					return a.connector < b.connector
				}
				return a.tool < b.tool
			})
			results := []map[string]any{}
			for i := 0; i < len(matches) && i < limit; i++ {
				results = append(results, matches[i].result)
			}
			return map[string]any{"results": results, "searched_connectors": len(connectors)}, nil
		}},
		"call": {title: "Call connector tool", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Connector string          `json:"connector"`
				Tool      string          `json:"tool"`
				Arguments json.RawMessage `json:"arguments"`
				Confirm   bool            `json:"confirm"`
			}](args)
			if err != nil {
				return nil, err
			}
			arguments := in.Arguments
			if len(arguments) == 0 || string(arguments) == "null" {
				arguments = json.RawMessage(`{}`)
			}
			res, err := t.Call(ctx, c, in.Connector, in.Tool, arguments, in.Confirm)
			if err != nil {
				return nil, connectorCallError(in.Connector, in.Tool, err)
			}
			switch {
			case res.ActionRequired != nil:
				return map[string]any{"connector_id": res.ConnectorID, "connector": res.Connector, "action_required": connectActionJSON(res.ActionRequired)}, nil
			case res.ConfirmationRequired:
				return map[string]any{"confirmation_required": true, "connector": res.Connector, "tool": res.Tool, "message": confirmMessage}, nil
			}
			content := res.Content
			if content == nil {
				content = []map[string]any{}
			}
			out := map[string]any{"connector_id": res.ConnectorID, "connector": res.Connector, "tool": res.Tool, "content": content}
			if res.StructuredContent != nil {
				out["structuredContent"] = res.StructuredContent
			}
			if res.IsError {
				out["is_error"] = true
			}
			return out, nil
		}},
	}
}

// closeMatches is difflib.get_close_matches(word, possibilities, n, cutoff):
// the best candidates whose SequenceMatcher ratio reaches cutoff, best first.
func closeMatches(word string, possibilities []string, n int, cutoff float64) []string {
	type scored struct {
		score float64
		x     string
	}
	b := []rune(word)
	var result []scored
	for _, x := range possibilities {
		a := []rune(x)
		if r := matchRatio(a, b); r >= cutoff {
			result = append(result, scored{r, x})
		}
	}
	sort.SliceStable(result, func(i, j int) bool {
		if result[i].score != result[j].score {
			return result[i].score > result[j].score
		}
		return result[i].x > result[j].x
	})
	out := []string{}
	for i := 0; i < len(result) && i < n; i++ {
		out = append(out, result[i].x)
	}
	return out
}

// matchRatio is SequenceMatcher(None, a, b).ratio(): 2*M/T over the
// Ratcliff/Obershelp matching blocks.
func matchRatio(a, b []rune) float64 {
	total := len(a) + len(b)
	if total == 0 {
		return 1
	}
	b2j := map[rune][]int{}
	for j, r := range b {
		b2j[r] = append(b2j[r], j)
	}
	if len(b) >= 200 {
		ntest := len(b)/100 + 1
		for r, js := range b2j {
			if len(js) > ntest {
				delete(b2j, r)
			}
		}
	}
	longest := func(alo, ahi, blo, bhi int) (int, int, int) {
		besti, bestj, bestsize := alo, blo, 0
		j2len := map[int]int{}
		for i := alo; i < ahi; i++ {
			next := map[int]int{}
			for _, j := range b2j[a[i]] {
				if j < blo {
					continue
				}
				if j >= bhi {
					break
				}
				k := j2len[j-1] + 1
				next[j] = k
				if k > bestsize {
					besti, bestj, bestsize = i-k+1, j-k+1, k
				}
			}
			j2len = next
		}
		return besti, bestj, bestsize
	}
	matches := 0
	queue := [][4]int{{0, len(a), 0, len(b)}}
	for len(queue) > 0 {
		q := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		i, j, k := longest(q[0], q[1], q[2], q[3])
		if k == 0 {
			continue
		}
		matches += k
		if q[0] < i && q[2] < j {
			queue = append(queue, [4]int{q[0], i, q[2], j})
		}
		if i+k < q[1] && j+k < q[3] {
			queue = append(queue, [4]int{i + k, q[1], j + k, q[3]})
		}
	}
	return 2 * float64(matches) / float64(total)
}
