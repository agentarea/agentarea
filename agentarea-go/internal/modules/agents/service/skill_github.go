package service

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// SkillCodeloadBase is github_git.CODELOAD: the archive host a tokenless import reads.
const SkillCodeloadBase = "https://codeload.github.com"

const skillGitHubTimeout = 30 * time.Second

// skillQuote is urllib.parse.quote(s, safe=""): everything but unreserved characters escaped.
func skillQuote(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || strings.IndexByte("_.-~", c) >= 0 {
			b.WriteByte(c)
			continue
		}
		fmt.Fprintf(&b, "%%%02X", c)
	}
	return b.String()
}

// downloadRepo is download_repo without a token: the archive endpoint, no
// REST call, no redirect followed, refused past the repository ZIP cap.
func (k *Skills) downloadRepo(ctx context.Context, githubURL string) ([]byte, error) {
	info, err := domain.SkillParseGitHubURL(githubURL)
	if err != nil {
		return nil, err
	}
	if !domain.SkillCheckRepoPart(info.Owner) || !domain.SkillCheckRepoPart(info.Repo) {
		return nil, &domain.SkillGitHubError{Kind: domain.SkillGitHubInvalidURL, Msg: "Not a GitHub repository: " + info.Owner + "/" + info.Repo}
	}
	if k.github == nil {
		return nil, &UnwiredError{Feature: "outbound requests to GitHub"}
	}
	ref := "HEAD"
	if info.Branch != nil {
		ref = *info.Branch
	}
	u := SkillCodeloadBase + "/" + info.Owner + "/" + info.Repo + "/zip/" + skillQuote(ref)
	client := &http.Client{Transport: k.github, Timeout: skillGitHubTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, &domain.SkillGitHubError{Msg: "Error downloading repository: " + err.Error()}
	}
	resp, err := client.Do(req)
	if err != nil {
		var ne net.Error
		if errors.As(err, &ne) && ne.Timeout() {
			return nil, &domain.SkillGitHubError{Msg: "Timeout downloading repository: " + err.Error()}
		}
		return nil, &domain.SkillGitHubError{Msg: "Error downloading repository: " + err.Error()}
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		text, _ := io.ReadAll(io.LimitReader(resp.Body, domain.SkillMaxRepoZipBytes))
		return nil, skillCheckResponse(resp, string(text))
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, domain.SkillMaxRepoZipBytes+1))
	if err != nil {
		return nil, &domain.SkillGitHubError{Msg: "Error downloading repository: " + err.Error()}
	}
	if len(body) > domain.SkillMaxRepoZipBytes {
		return nil, &domain.SkillValueError{Msg: fmt.Sprintf("GitHub repository ZIP exceeds %d MB limit", domain.SkillMaxRepoZipBytes/(1024*1024))}
	}
	return body, nil
}

// skillCheckResponse is _check_response for a status other than 200.
func skillCheckResponse(resp *http.Response, text string) error {
	switch resp.StatusCode {
	case http.StatusTooManyRequests:
		return &domain.SkillGitHubError{Kind: domain.SkillGitHubRateLimited, Msg: "GitHub throttled the request; retry later."}
	case http.StatusForbidden:
		remaining := resp.Header.Get("X-RateLimit-Remaining")
		if _, ok := resp.Header["X-Ratelimit-Remaining"]; !ok {
			remaining = "0"
		}
		if remaining == "0" {
			reset := resp.Header.Get("X-RateLimit-Reset")
			if _, ok := resp.Header["X-Ratelimit-Reset"]; !ok {
				reset = "unknown"
			}
			return &domain.SkillGitHubError{Kind: domain.SkillGitHubRateLimited, Msg: "GitHub API rate limit exceeded. Resets at " + reset +
				". Consider providing a GitHub token for higher limits."}
		}
		return &domain.SkillGitHubError{Msg: "Access forbidden: " + text}
	case http.StatusNotFound:
		return &domain.SkillGitHubError{Kind: domain.SkillGitHubNotFound, Msg: "Repository not found. It may be private or the URL may be incorrect."}
	case http.StatusUnauthorized:
		return &domain.SkillGitHubError{Msg: "Authentication failed. Check your GitHub token."}
	}
	return &domain.SkillGitHubError{Msg: fmt.Sprintf("GitHub API error: %d - %s", resp.StatusCode, text)}
}
