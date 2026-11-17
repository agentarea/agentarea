package domain

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"
)

// attributionMaxLen is the width of every attribution column.
const attributionMaxLen = 64

// Channels are the acquisition channels a sign-up is counted under (ADR-0047).
func Channels() []string {
	return []string{"campaign", "search", "social", "referral", "skills_catalog", "direct"}
}

func searchHosts() []string { return []string{"google.", "yandex.", "bing.com", "duckduckgo.com"} }

func socialHosts() []string {
	return []string{"t.me", "telegram.org", "x.com", "twitter.com", "linkedin.com", "reddit.com",
		"news.ycombinator.com", "youtube.com", "vc.ru", "habr.com"}
}

func skillsPaths() []string { return []string{"/skills/", "/ru/skills/"} }

func patternedPaths() []string { return []string{"/ru/skills/", "/skills/", "/ru/blog/", "/blog/"} }

// Attribution is the first touch of the visit that brought a sign-up.
type Attribution struct {
	Channel      string
	ReferrerHost *string
	LandingHost  *string
	LandingPath  *string
	UTMSource    *string
	UTMMedium    *string
	UTMCampaign  *string
}

func clip(v string) *string {
	v = strings.TrimSpace(v)
	if utf8.RuneCountInString(v) > attributionMaxLen {
		v = string([]rune(v)[:attributionMaxLen])
	}
	if v == "" {
		return nil
	}
	return &v
}

// PathPattern is path_pattern: /skills/*, /blog/* (and their /ru twins), else the path itself.
func PathPattern(path *string) *string {
	if path == nil || *path == "" {
		return nil
	}
	for _, prefix := range patternedPaths() {
		if strings.HasPrefix(*path, prefix) {
			p := prefix + "*"
			return &p
		}
	}
	return clip(*path)
}

func ownHost(host string, own []string) bool {
	for _, d := range own {
		if host == d || strings.HasSuffix(host, "."+d) {
			return true
		}
	}
	return false
}

func searchHost(host string) bool {
	for _, s := range searchHosts() {
		if strings.HasPrefix(host, s) || strings.Contains(host, "."+s) {
			return true
		}
	}
	return false
}

// ClassifyChannel is classify_channel: the first rule of ADR-0047's table that holds. A referrer
// at one of own or below it is the installation's own site, not a channel.
func ClassifyChannel(referrerHost, landingPath, utmSource *string, own []string) string {
	if utmSource != nil && *utmSource != "" {
		return "campaign"
	}
	if referrerHost != nil && *referrerHost != "" {
		host := strings.TrimPrefix(strings.ToLower(*referrerHost), "www.")
		if !ownHost(host, own) {
			switch {
			case searchHost(host):
				return "search"
			case slices.Contains(socialHosts(), host):
				return "social"
			}
			return "referral"
		}
	}
	if landingPath != nil {
		for _, p := range skillsPaths() {
			if strings.HasPrefix(*landingPath, p) {
				return "skills_catalog"
			}
		}
	}
	return "direct"
}

// AttributionFromRequestURL is attribution_from_request_url: the landing's aa_* and utm_*
// parameters; a declared channel is kept only when it is a known one.
func AttributionFromRequestURL(requestURL *string, own []string) Attribution {
	var query url.Values
	if requestURL != nil {
		if u, err := url.Parse(*requestURL); err == nil {
			query, _ = url.ParseQuery(u.RawQuery)
		}
	}
	first := func(name string) *string {
		for _, v := range query[name] {
			if v != "" {
				return clip(v)
			}
		}
		return nil
	}
	referrer, landingPath, utmSource := first("aa_ref"), first("aa_lp"), first("utm_source")
	channel := ""
	if declared := first("aa_ch"); declared != nil && slices.Contains(Channels(), *declared) {
		channel = *declared
	} else {
		channel = ClassifyChannel(referrer, landingPath, utmSource, own)
	}
	return Attribution{Channel: channel, ReferrerHost: referrer, LandingHost: first("aa_lh"), LandingPath: PathPattern(landingPath),
		UTMSource: utmSource, UTMMedium: first("utm_medium"), UTMCampaign: first("utm_campaign")}
}

var domainLabel = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)

// ParseOwnDomains is parse_domains: "example.com,example.org" as lower-case domain names;
// empty is none.
func ParseOwnDomains(raw string) ([]string, error) {
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	var out []string
	for _, entry := range strings.Split(raw, ",") {
		d := strings.ToLower(strings.TrimSpace(entry))
		labels := strings.Split(d, ".")
		ok := len(labels) >= 2
		for _, l := range labels {
			ok = ok && domainLabel.MatchString(l)
		}
		if !ok || labels[len(labels)-1][0] < 'a' || labels[len(labels)-1][0] > 'z' {
			return nil, fmt.Errorf("%q is not a domain name such as example.com", entry)
		}
		out = append(out, d)
	}
	return out, nil
}

// SignupMethod is the registration method a sign-up records: password, oidc or code, else none.
func SignupMethod(method string) *string {
	switch method {
	case "password", "oidc", "code":
		return &method
	}
	return nil
}

// Pseudonymize is pseudonymize: value keyed by the installation, countable inside it and
// unlinkable outside it.
func Pseudonymize(installID, value string) string {
	mac := hmac.New(sha256.New, []byte(installID))
	mac.Write([]byte(value))
	return hex.EncodeToString(mac.Sum(nil))[:16]
}
