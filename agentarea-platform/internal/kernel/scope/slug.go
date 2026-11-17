package scope

import (
	"fmt"
	"strings"

	"golang.org/x/text/unicode/norm"
)

const (
	// WorkspaceSlugMaxLength bounds a slug minted from a name (workspaces/slug.py SLUG_MAX_LENGTH).
	WorkspaceSlugMaxLength = 40
	// WorkspaceSlugColumnLength bounds what a URL may name as a workspace:
	// collision suffixes and slugs backfilled from ids fit the 120-char column.
	WorkspaceSlugColumnLength = 120
	// EntitySlugMaxLength bounds an entity slug (utils/slug.py _MAX_SLUG_LENGTH).
	EntitySlugMaxLength = 100
	// EntitySlugFallback is the slug of a name with nothing slug-able in it.
	EntitySlugFallback = "item"
	// MaxSlugCollisionSuffix is the last suffix UniqueSlug tries (base-999).
	MaxSlugCollisionSuffix = 999
)

// IsUUIDShaped reports whether reference looks like a workspace id rather than
// a slug. A personal workspace's id is its owner's user id, so a slug of this
// shape could impersonate one and is never minted.
func IsUUIDShaped(reference string) bool {
	r := strings.ToLower(reference)
	if len(r) != 36 {
		return false
	}
	for i := range len(r) {
		c := r[i]
		switch i {
		case 8, 13, 18, 23:
			if c != '-' {
				return false
			}
		default:
			if !isHexLower(c) {
				return false
			}
		}
	}
	return true
}

// ValidWorkspaceSlug reports whether reference could name a workspace in a
// URL: ^[a-z0-9]+(?:-[a-z0-9]+)*$ and at most WorkspaceSlugColumnLength chars.
func ValidWorkspaceSlug(reference string) bool {
	if reference == "" || len(reference) > WorkspaceSlugColumnLength {
		return false
	}
	prevHyphen := true
	for i := range len(reference) {
		c := reference[i]
		switch {
		case isAlnumLower(c):
			prevHyphen = false
		case c == '-' && !prevHyphen:
			prevHyphen = true
		default:
			return false
		}
	}
	return !prevHyphen
}

// SlugifyWorkspace lowercases, hyphenates and trims text into a workspace
// slug. It never returns an empty string (fallback instead) nor a UUID-shaped
// one (suffixed with "-ws"). Matches workspaces/slug.py slugify.
func SlugifyWorkspace(text, fallback string) string {
	base := strings.Trim(hyphenate(pythonLower(text)), "-")
	if len(base) > WorkspaceSlugMaxLength {
		base = base[:WorkspaceSlugMaxLength]
	}
	base = strings.Trim(base, "-")
	if base == "" {
		base = fallback
	}
	if IsUUIDShaped(base) {
		return base + "-ws"
	}
	return base
}

// EntitySlug derives a workspace-scoped entity slug from a name: NFKD, ASCII
// only, lowercase, runs of anything else to one hyphen, trimmed, at most
// EntitySlugMaxLength, EntitySlugFallback when empty. Matches utils/slug.py
// generate_slug. A slug is derived once at creation and never on rename.
func EntitySlug(name string) string {
	decomposed := norm.NFKD.String(name)
	ascii := make([]byte, 0, len(decomposed))
	for i := range len(decomposed) {
		if decomposed[i] < 0x80 {
			ascii = append(ascii, decomposed[i])
		}
	}
	slug := strings.Trim(hyphenate(strings.ToLower(string(ascii))), "-")
	if len(slug) > EntitySlugMaxLength {
		slug = strings.TrimRight(slug[:EntitySlugMaxLength], "-")
	}
	if slug == "" {
		return EntitySlugFallback
	}
	return slug
}

// UniqueSlug returns base when it is free, otherwise base-2, base-3, ... up to
// base-MaxSlugCollisionSuffix (utils/slug.py ensure_unique_slug).
func UniqueSlug(base string, exists func(candidate string) (bool, error)) (string, error) {
	taken, err := exists(base)
	if err != nil || !taken {
		return base, err
	}
	for suffix := 2; suffix <= MaxSlugCollisionSuffix; suffix++ {
		candidate := fmt.Sprintf("%s-%d", base, suffix)
		taken, err := exists(candidate)
		if err != nil {
			return "", err
		}
		if !taken {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("exhausted collision suffixes (-2..-%d) for slug base '%s'", MaxSlugCollisionSuffix, base)
}

// hyphenate replaces every run of characters outside [a-z0-9] with one '-'.
func hyphenate(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	run := false
	for i := range len(s) {
		c := s[i]
		if isAlnumLower(c) {
			b.WriteByte(c)
			run = false
			continue
		}
		if !run {
			b.WriteByte('-')
			run = true
		}
	}
	return b.String()
}

// pythonLower is str.lower(): Go maps U+0130 to "i", Python to "i" + U+0307.
func pythonLower(s string) string {
	return strings.ToLower(strings.ReplaceAll(s, "İ", "i̇"))
}

func isAlnumLower(c byte) bool { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') }

func isHexLower(c byte) bool { return (c >= 'a' && c <= 'f') || (c >= '0' && c <= '9') }
