package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// a2aCardTimeout is _CARD_TIMEOUT.
const a2aCardTimeout = 10 * time.Second

// A2ACardFetchError is read_agent_card's 400: no card could be read at Address.
type A2ACardFetchError struct {
	Address string
	Reason  string
}

func (e *A2ACardFetchError) Error() string { return "No agent card at " + e.Address + ": " + e.Reason }

// ReadCard is read_agent_card: the card published at the agent's address,
// fetched through the outbound guard; its address, name, description and skills.
func (a *A2A) ReadCard(ctx context.Context, rawURL string) (domain.A2AJSON, error) {
	if a.d.Outbound == nil {
		return nil, &UnwiredError{Feature: "Reading an agent card"}
	}
	address := domain.A2ACardAddress(rawURL)
	target := strings.TrimRight(address, "/") + "/.well-known/agent-card.json"
	ctx, cancel := context.WithTimeout(ctx, a2aCardTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Invalid agent card URL %s: %s", target, a2aNetworkReason(err))}
	}
	client := &http.Client{Transport: a.d.Outbound, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	resp, err := client.Do(req)
	if err != nil {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Network communication error fetching agent card from %s: %s", target, a2aNetworkReason(err))}
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Failed to fetch agent card from %s (HTTP %d): %s", target, resp.StatusCode, a2aStatusMessage(resp, target))}
	}
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Network communication error fetching agent card from %s: %s", target, a2aNetworkReason(err))}
	}
	decodeErr, ok := wirejson.Check(raw)
	if !ok {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Failed to parse JSON for agent card from %s: the body is not UTF-8", target)}
	}
	if decodeErr != nil {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Failed to parse JSON for agent card from %s: %s", target, A2AJSONDecodeMessage(raw, decodeErr))}
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Failed to parse JSON for agent card from %s: %s", target, err)}
	}
	card, isObject := A2AFromWire(v).(domain.A2AJSON)
	if !isObject {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Failed to validate agent card structure from %s: the card is not a JSON object", target)}
	}
	summary, reason := a2aCardSummary(card)
	if reason != "" {
		return nil, &A2ACardFetchError{Address: address, Reason: fmt.Sprintf("Failed to validate agent card structure from %s: %s", target, reason)}
	}
	return append(domain.A2AJSON{{Key: "address", Value: address}}, summary...), nil
}

// A2AJSONDecodeMessage is str(json.JSONDecodeError): the message with line,
// column and character position.
func A2AJSONDecodeMessage(raw []byte, e *wirejson.DecodeError) string {
	doc := []rune(strings.TrimPrefix(string(raw), "\xef\xbb\xbf"))
	pos := min(max(e.Pos, 0), len(doc))
	line, last := 1, -1
	for i, r := range doc[:pos] {
		if r == '\n' {
			line++
			last = i
		}
	}
	return fmt.Sprintf("%s: line %d column %d (char %d)", e.Msg, line, pos-last, e.Pos)
}

func a2aNetworkReason(err error) string {
	var ue *url.Error
	if errors.As(err, &ue) {
		err = ue.Err
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return "timed out"
	}
	return err.Error()
}

// a2aStatusMessage is httpx's raise_for_status message.
func a2aStatusMessage(resp *http.Response, target string) string {
	phrase := strings.TrimSpace(strings.TrimPrefix(resp.Status, strconv.Itoa(resp.StatusCode)))
	kind := map[int]string{1: "Informational response", 3: "Redirect response", 4: "Client error", 5: "Server error"}[resp.StatusCode/100]
	if kind == "" {
		kind = "Invalid status code"
	}
	msg := fmt.Sprintf("%s '%d %s' for url '%s'\n", kind, resp.StatusCode, phrase, target)
	switch resp.StatusCode {
	case 301, 302, 303, 307, 308:
		if loc := resp.Header.Values("Location"); len(loc) > 0 {
			msg += fmt.Sprintf("Redirect location: '%s'\n", loc[0])
		}
	}
	return msg + fmt.Sprintf("For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/%d", resp.StatusCode)
}

func a2aStringField(o domain.A2AJSON, key string) (string, string) {
	v, ok := o.Get(key)
	if !ok || v == nil {
		return "", ""
	}
	s, isStr := v.(string)
	if !isStr {
		return "", fmt.Sprintf("Failed to parse %s field: expected string or bytes-like object, got '%s'.", key, a2aTypeName(v))
	}
	if !utf8.ValidString(s) {
		return "", fmt.Sprintf("Failed to parse %s field: Unpaired surrogate at AgentCard.%s.", key, key)
	}
	return s, ""
}

func a2aTypeName(v any) string {
	switch v.(type) {
	case bool:
		return "bool"
	case string:
		return "str"
	case float64:
		return "float"
	case domain.A2AJSON:
		return "dict"
	case []any:
		return "list"
	}
	return "int"
}

// a2aCardSummary is parse_agent_card's ParseDict over the fields read_agent_card
// reads (name, description, skills[].name, skills[].description); the reason
// names the first one that does not parse.
func a2aCardSummary(card domain.A2AJSON) (domain.A2AJSON, string) {
	name, reason := a2aStringField(card, "name")
	if reason != "" {
		return nil, reason
	}
	description, reason := a2aStringField(card, "description")
	if reason != "" {
		return nil, reason
	}
	skills := []any{}
	if v, ok := card.Get("skills"); ok && v != nil {
		list, isList := v.([]any)
		if !isList {
			return nil, fmt.Sprintf("Failed to parse skills field: repeated field skills must be in [] which is %v at AgentCard.", v)
		}
		for i, e := range list {
			skill, isObject := e.(domain.A2AJSON)
			if !isObject {
				return nil, fmt.Sprintf("Failed to parse skills field: skill %d is not an object.", i)
			}
			sn, reason := a2aStringField(skill, "name")
			if reason != "" {
				return nil, "Failed to parse skills field: " + reason
			}
			sd, reason := a2aStringField(skill, "description")
			if reason != "" {
				return nil, "Failed to parse skills field: " + reason
			}
			skills = append(skills, domain.A2AJSON{{Key: "name", Value: sn}, {Key: "description", Value: sd}})
		}
	}
	return domain.A2AJSON{{Key: "name", Value: name}, {Key: "description", Value: description}, {Key: "skills", Value: skills}}, ""
}
