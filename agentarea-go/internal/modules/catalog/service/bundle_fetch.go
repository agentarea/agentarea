package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

const bundleFetchTimeout = 10 * time.Second

// BundleSourceError is a source_url the analyze refused or could not read: a 400.
type BundleSourceError struct{ Msg string }

func (e *BundleSourceError) Error() string { return e.Msg }

var errBundleFetchUnwired = errors.New("catalog bundles: source_url fetching needs the outbound clients")

// pyDecodeReplace is bytes.decode("utf-8", errors="replace").
func pyDecodeReplace(b []byte) string {
	var sb strings.Builder
	for len(b) > 0 {
		r, size := utf8.DecodeRune(b)
		if r == utf8.RuneError && size <= 1 {
			sb.WriteRune(utf8.RuneError)
			b = b[1:]
			continue
		}
		sb.Write(b[:size])
		b = b[size:]
	}
	return sb.String()
}

// FetchSource is fetch_bundle_source: the URL vetted, the pinned member client,
// no redirects, a 10 s timeout and a 5MB cap.
func (b *Bundles) FetchSource(ctx context.Context, rawURL string) (string, error) {
	if b.d.Guard == nil || b.d.Net == nil {
		return "", errBundleFetchUnwired
	}
	if _, err := b.d.Guard().CheckURL(ctx, rawURL); err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			return "", &BundleSourceError{Msg: err.Error()}
		}
		return "", err
	}
	client := &http.Client{Transport: b.d.Net.Transport(netguard.Member), Timeout: bundleFetchTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return "", &BundleSourceError{Msg: err.Error()}
	}
	failed := func(err error) error {
		if errors.Is(err, netguard.ErrUnsafe) {
			return &BundleSourceError{Msg: err.Error()}
		}
		b.d.Log.ErrorContext(ctx, "Failed to fetch bundle", "url", strings.NewReplacer("\r", "", "\n", "").Replace(rawURL), "error", err)
		return &BundleSourceError{Msg: "failed to fetch bundle from the provided URL"}
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", failed(err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return "", &BundleSourceError{Msg: fmt.Sprintf("bundle URL returned HTTP %d", resp.StatusCode)}
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, BundleMaxBytes+1))
	if err != nil {
		return "", failed(err)
	}
	if len(body) > BundleMaxBytes {
		return "", &BundleSourceError{Msg: "bundle source exceeds 5MB limit"}
	}
	return pyDecodeReplace(body), nil
}
