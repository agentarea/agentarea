package domain

import (
	"fmt"
	"slices"
	"strings"
)

// Transports, auth styles, reasoning params and list shapes a provider spec names (provider_profiles.py).
const (
	TransportOpenAI    = "openai"
	TransportAnthropic = "anthropic"

	AuthBearer       = "bearer"
	AuthAPIKeyHeader = "api_key_header"
	AuthNone         = "none"

	ReasoningEffortParam = "reasoning_effort"
	ReasoningObjectParam = "reasoning"

	ListDataID     = "data_id"
	ListModelsName = "models_name"

	anthropicAPIVersion = "2023-06-01"
)

// Profile is one provider's HTTP contract (ProviderProfile).
type Profile struct {
	BaseURL          string
	Transport        string
	Auth             string
	ModelsPath       string
	ListShape        string
	ModelsQuery      string
	ReasoningParam   string
	ReasoningLevels  []string
	CacheBreakpoints bool
}

// ProfileError is a stored value ProviderProfile.from_mapping refuses.
type ProfileError struct{ Msg string }

func (e *ProfileError) Error() string { return e.Msg }

// PyType is the class Python raises.
func (e *ProfileError) PyType() string { return "ValueError" }

// NewProfile is ProviderProfile.from_mapping: empty values take the defaults,
// an unknown enum value is refused.
func NewProfile(p Profile) (Profile, error) {
	pick := func(v, def string, allowed ...string) (string, error) {
		if v == "" {
			return def, nil
		}
		if !slices.Contains(allowed, v) {
			return "", &ProfileError{Msg: fmt.Sprintf("'%s' is not a valid value", v)}
		}
		return v, nil
	}
	var err error
	if p.Transport, err = pick(p.Transport, TransportOpenAI, TransportOpenAI, TransportAnthropic); err != nil {
		return Profile{}, err
	}
	if p.Auth, err = pick(p.Auth, AuthBearer, AuthBearer, AuthAPIKeyHeader, AuthNone); err != nil {
		return Profile{}, err
	}
	if p.ListShape, err = pick(p.ListShape, ListDataID, ListDataID, ListModelsName); err != nil {
		return Profile{}, err
	}
	if p.ReasoningParam, err = pick(p.ReasoningParam, ReasoningEffortParam, ReasoningEffortParam, ReasoningObjectParam); err != nil {
		return Profile{}, err
	}
	for _, l := range p.ReasoningLevels {
		if l == "" {
			return Profile{}, &ProfileError{Msg: "reasoning_efforts must be a list of level names"}
		}
	}
	return p, nil
}

// RequiresEndpointURL: the provider is self-hosted and only the operator knows where.
func (p Profile) RequiresEndpointURL() bool { return p.BaseURL == "" }

// RequiresAPIKey: the provider authenticates callers at all.
func (p Profile) RequiresAPIKey() bool { return p.Auth != AuthNone }

func withScheme(u string) string {
	u = strings.TrimRight(u, "/")
	if strings.HasPrefix(u, "http://") || strings.HasPrefix(u, "https://") {
		return u
	}
	return "http://" + u
}

// APIRoot is the root a call goes to; "" when there is no address. A typed
// endpoint may be the server root or its /v1; the catalog's base_url is used exactly.
func (p Profile) APIRoot(endpointURL string) string {
	if endpointURL != "" {
		root := withScheme(endpointURL)
		if strings.HasSuffix(root, "/v1") {
			return root
		}
		return root + "/v1"
	}
	return strings.TrimRight(p.BaseURL, "/")
}

// APIURL is the full URL of path, "" when there is no address.
func (p Profile) APIURL(endpointURL, path string) string {
	root := p.APIRoot(endpointURL)
	if root == "" {
		return ""
	}
	return root + path
}

// ModelsURL is resolve_models_url.
func (p Profile) ModelsURL(endpointURL string) string {
	var u string
	if p.ModelsPath != "" {
		address := endpointURL
		if address == "" {
			address = p.BaseURL
		}
		if address == "" {
			return ""
		}
		u = withScheme(address) + p.ModelsPath
	} else {
		root := p.APIRoot(endpointURL)
		if root == "" {
			return ""
		}
		u = root + "/models"
	}
	if p.ModelsQuery != "" {
		return u + "?" + p.ModelsQuery
	}
	return u
}

// ReasoningSettingError is a level or budget the model or provider cannot take; retrying cannot help.
type ReasoningSettingError struct{ Msg string }

func (e *ReasoningSettingError) Error() string { return e.Msg }

// PyType is the class Python raises.
func (e *ReasoningSettingError) PyType() string { return "ReasoningSettingError" }

// CheckEffort refuses a level the catalog says the model does not take; no levels, no check.
func CheckEffort(effort string, levels []string, modelName string) error {
	if effort != "" && len(levels) > 0 && !slices.Contains(levels, effort) {
		return &ReasoningSettingError{Msg: fmt.Sprintf("model %s takes reasoning_effort %s, not %s", modelName, strings.Join(levels, ", "), effort)}
	}
	return nil
}

// ReasoningFields are the request fields asking for a level or a budget.
func (p Profile) ReasoningFields(effort string, maxTokens *int) (map[string]any, error) {
	budget := maxTokens != nil && *maxTokens != 0
	if effort != "" && budget {
		return nil, &ReasoningSettingError{Msg: "set reasoning_effort or reasoning_max_tokens, not both"}
	}
	if p.ReasoningParam == ReasoningObjectParam {
		switch {
		case effort != "":
			return map[string]any{"reasoning": map[string]any{"effort": effort}}, nil
		case budget:
			return map[string]any{"reasoning": map[string]any{"max_tokens": *maxTokens}}, nil
		}
		return nil, nil
	}
	if budget {
		return nil, &ReasoningSettingError{Msg: "this provider takes a reasoning level (reasoning_effort), not a token budget"}
	}
	if effort != "" {
		return map[string]any{"reasoning_effort": effort}, nil
	}
	return nil, nil
}

// Headers are the auth headers, none when there is nothing to send.
func (p Profile) Headers(apiKey string) map[string]string {
	if apiKey == "" || p.Auth == AuthNone {
		return map[string]string{}
	}
	if p.Auth == AuthAPIKeyHeader {
		return map[string]string{"x-api-key": apiKey, "anthropic-version": anthropicAPIVersion}
	}
	return map[string]string{"Authorization": "Bearer " + apiKey}
}

// CheckEndpointURL is _checked_endpoint_url's shape check over urlsplit: the
// refusal message, "" when the address is acceptable.
func CheckEndpointURL(v string) string {
	scheme, rest := "", v
	if i := strings.IndexByte(v, ':'); i > 0 {
		valid := true
		for j, c := range v[:i] {
			alpha := (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
			if !alpha && (j == 0 || ((c < '0' || c > '9') && c != '+' && c != '-' && c != '.')) {
				valid = false
				break
			}
		}
		if valid {
			scheme, rest = strings.ToLower(v[:i]), v[i+1:]
		}
	}
	netloc := ""
	if strings.HasPrefix(rest, "//") {
		rest = rest[2:]
		end := strings.IndexAny(rest, "/?#")
		if end < 0 {
			end = len(rest)
		}
		netloc, rest = rest[:end], rest[end:]
	}
	if strings.Contains(netloc, "[") != strings.Contains(netloc, "]") {
		return "Invalid IPv6 URL"
	}
	host := netloc
	if i := strings.LastIndexByte(host, '@'); i >= 0 {
		host = host[i+1:]
	}
	if strings.HasPrefix(host, "[") {
		if i := strings.IndexByte(host, ']'); i >= 0 {
			host = host[1:i]
		}
	} else if i := strings.IndexByte(host, ':'); i >= 0 {
		host = host[:i]
	}
	if (scheme != "http" && scheme != "https") || host == "" {
		return "endpoint_url must be an http or https URL with a host"
	}
	query, fragment := "", ""
	if i := strings.IndexByte(rest, '#'); i >= 0 {
		fragment, rest = rest[i+1:], rest[:i]
	}
	if i := strings.IndexByte(rest, '?'); i >= 0 {
		query = rest[i+1:]
	}
	trimmed := strings.TrimRightFunc(v, func(r rune) bool {
		return r == ' ' || (r >= '\t' && r <= '\r') || (r >= 0x1c && r <= 0x1f) || r == 0x85 || r == 0xa0
	})
	if query != "" || fragment != "" || strings.HasSuffix(trimmed, "?") || strings.HasSuffix(trimmed, "#") {
		return "endpoint_url must not contain a query string or fragment"
	}
	return ""
}
