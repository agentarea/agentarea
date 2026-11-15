package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
)

// ErrDirectoryUnavailable is a Kratos that could not be asked
// (IdentityDirectoryUnavailableError).
var ErrDirectoryUnavailable = errors.New("identity directory unavailable")

// Kratos admin lookups (auth/identity_directory.py KratosIdentityDirectory).
const (
	MaxConcurrentLookups = 8
	DirectoryTimeout     = 5 * time.Second
)

// Kratos resolves user ids through the Kratos admin API
// (AGENTAREA_AUTH_KRATOS_ADMIN_URL).
type Kratos struct {
	adminURL string
	client   *http.Client
	log      *slog.Logger
}

// NewKratos builds the directory; adminURL must not be blank.
func NewKratos(adminURL string, client *http.Client, log *slog.Logger) (*Kratos, error) {
	u := strings.TrimRight(strings.TrimSpace(adminURL), "/")
	if u == "" {
		return nil, errors.New("admin_url is required to resolve identities")
	}
	if client == nil {
		client = &http.Client{Timeout: DirectoryTimeout}
	}
	if log == nil {
		log = slog.Default()
	}
	return &Kratos{adminURL: u, client: client, log: log}, nil
}

// Resolve maps each resolvable id to its identity; ids Kratos has no entry
// for, or could not be asked about, are absent.
func (k *Kratos) Resolve(ctx context.Context, userIDs []string) (map[string]domain.Identity, error) {
	seen := map[string]bool{}
	var unique []string
	for _, id := range userIDs {
		if id != "" && !seen[id] {
			seen[id] = true
			unique = append(unique, id)
		}
	}
	out := map[string]domain.Identity{}
	var mu sync.Mutex
	var wg sync.WaitGroup
	sem := make(chan struct{}, MaxConcurrentLookups)
	for _, id := range unique {
		wg.Go(func() {
			sem <- struct{}{}
			defer func() { <-sem }()
			rec, err := k.Lookup(ctx, id)
			if err != nil {
				k.log.ErrorContext(ctx, "Identity lookup failed for user", "user_id", id, "error", err)
				return
			}
			if rec != nil {
				mu.Lock()
				out[id] = *rec
				mu.Unlock()
			}
		})
	}
	wg.Wait()
	return out, nil
}

// Lookup is one identity, nil when Kratos has none; ErrDirectoryUnavailable
// when it could not answer.
func (k *Kratos) Lookup(ctx context.Context, userID string) (*domain.Identity, error) {
	ctx, cancel := context.WithTimeout(ctx, DirectoryTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, k.adminURL+"/admin/identities/"+quoteSegment(userID), nil)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrDirectoryUnavailable, err)
	}
	resp, err := k.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: Kratos unreachable: %w", ErrDirectoryUnavailable, err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode == http.StatusNotFound {
		return nil, nil
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("%w: Kratos answered HTTP %d for user %s", ErrDirectoryUnavailable, resp.StatusCode, userID)
	}
	var body struct {
		Traits map[string]any `json:"traits"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, fmt.Errorf("%w: Kratos answered non-JSON for user %s", ErrDirectoryUnavailable, userID)
	}
	rec := RecordFromTraits(userID, body.Traits)
	return &rec, nil
}

// RecordFromTraits is _record_from_traits.
func RecordFromTraits(userID string, traits map[string]any) domain.Identity {
	rec := domain.Identity{UserID: userID}
	if e, _ := traits["email"].(string); e != "" {
		rec.Email = &e
	}
	if name := displayName(traits); name != "" {
		rec.DisplayName = &name
	} else {
		rec.DisplayName = rec.Email
	}
	return rec
}

func displayName(traits map[string]any) string {
	switch name := traits["name"].(type) {
	case map[string]any:
		var parts []string
		for _, k := range []string{"first", "last"} {
			if p, _ := name[k].(string); p != "" {
				parts = append(parts, p)
			}
		}
		if joined := strings.Join(parts, " "); joined != "" {
			return joined
		}
	case string:
		if s := strings.TrimSpace(name); s != "" {
			return s
		}
	}
	if u, ok := traits["username"].(string); ok {
		return strings.TrimSpace(u)
	}
	return ""
}

// quoteSegment is urllib.parse.quote(s, safe=""): only unreserved
// characters stay as they are.
func quoteSegment(s string) string {
	var b strings.Builder
	for i := range len(s) {
		c := s[i]
		if c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '.' || c == '-' || c == '~' {
			b.WriteByte(c)
			continue
		}
		fmt.Fprintf(&b, "%%%02X", c)
	}
	return b.String()
}
