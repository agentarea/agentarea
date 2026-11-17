package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
)

// folderDownloads is FOLDER_DOWNLOAD_CONCURRENCY.
const folderDownloads = 8

type apiTree struct {
	SHA       string         `json:"sha"`
	Truncated bool           `json:"truncated"`
	Tree      []apiTreeEntry `json:"tree"`
}

type apiTreeEntry struct {
	Path string `json:"path"`
	Type string `json:"type"`
	Mode string `json:"mode"`
	SHA  string `json:"sha"`
	Size int64  `json:"size"`
}

// apiCheck is GitHubSkillImporter._check_response.
func apiCheck(resp *http.Response) error {
	if resp.StatusCode == http.StatusOK {
		return nil
	}
	text, _ := io.ReadAll(io.LimitReader(resp.Body, rawReadBytes))
	switch resp.StatusCode {
	case http.StatusTooManyRequests:
		return &GitHubError{Msg: "GitHub throttled the request; retry later.", Status: 429, RateLimit: true}
	case http.StatusForbidden:
		remaining := resp.Header.Get("X-RateLimit-Remaining")
		if remaining == "" || remaining == "0" {
			reset := resp.Header.Get("X-RateLimit-Reset")
			if reset == "" {
				reset = "unknown"
			}
			return &GitHubError{Msg: "GitHub API rate limit exceeded. Resets at " + reset + ". Consider providing a GitHub token for higher limits.", Status: 429, RateLimit: true}
		}
		return &GitHubError{Msg: "Access forbidden: " + string(text), Status: 403}
	case http.StatusNotFound:
		return &GitHubError{Msg: "Repository not found. It may be private or the URL may be incorrect.", Status: 404}
	case http.StatusUnauthorized:
		return &GitHubError{Msg: "Authentication failed. Check your GitHub token.", Status: 401}
	}
	return &GitHubError{Msg: fmt.Sprintf("GitHub API error: %d - %s", resp.StatusCode, text), Status: resp.StatusCode}
}

func (x Installs) apiGet(ctx context.Context, token, u string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := x.Fetch.client(netguard.Vendor, githubTimeout, 10).Do(req)
	if err != nil {
		return &GitHubError{Msg: fmt.Sprintf("Error reading %s: %v", u, err)}
	}
	defer func() { _ = resp.Body.Close() }()
	if err := apiCheck(resp); err != nil {
		return err
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 64*1024*1024)).Decode(out); err != nil {
		return &GitHubError{Msg: "GitHub returned something this read cannot parse: " + u}
	}
	return nil
}

// tokenFolder is download_folder with a token: the commit and its recursive
// tree from the REST API, each file from raw.githubusercontent.com checked
// against its blob SHA.
func (x Installs) tokenFolder(ctx context.Context, token, repo, folder string, ref, treeSHA *string) (api.GitHubFolder, error) {
	if x.Fetch.Net == nil {
		return api.GitHubFolder{}, ErrNoOutbound
	}
	if err := checkedRepo(repo); err != nil {
		return api.GitHubFolder{}, err
	}
	folder = strings.Trim(folder, "/")
	where := repo
	if folder != "" {
		where += "/" + folder
	}
	base := x.Fetch.GitHub.API + "/repos/" + repo
	gone := func(err error) error {
		var gh *GitHubError
		if errors.As(err, &gh) && gh.Status == 404 {
			return &GitHubError{Msg: "The skill was removed upstream: " + repo + " is not on GitHub any more", Status: 404}
		}
		return err
	}
	commit := ""
	if ref != nil && gitSHA.MatchString(*ref) {
		commit = *ref
	} else {
		target, name := "HEAD", "'HEAD'"
		if ref != nil && *ref != "" {
			target, name = url.PathEscape(*ref), PyRepr(*ref)
		}
		var c struct {
			SHA string `json:"sha"`
		}
		if err := x.apiGet(ctx, token, base+"/commits/"+target, &c); err != nil {
			return api.GitHubFolder{}, gone(err)
		}
		if !gitSHA.MatchString(c.SHA) {
			return api.GitHubFolder{}, &GitHubError{Msg: base + " did not resolve " + name + " to a commit"}
		}
		commit = c.SHA
	}
	var tree apiTree
	if err := x.apiGet(ctx, token, base+"/git/trees/"+commit+"?recursive=1", &tree); err != nil {
		return api.GitHubFolder{}, gone(err)
	}
	entries, resolved := tree.Tree, tree.SHA
	if folder != "" {
		resolved = ""
		for _, e := range tree.Tree {
			if e.Path == folder && e.Type == "tree" {
				resolved = e.SHA
				break
			}
		}
		if resolved == "" {
			if tree.Truncated {
				return api.GitHubFolder{}, &GitHubError{Msg: repo + " is too large to list"}
			}
			return api.GitHubFolder{}, &GitHubError{Msg: fmt.Sprintf("The skill was removed upstream: %s is not in %s at %s", where, repo, commit), Status: 404}
		}
		entries = nil
		for _, e := range tree.Tree {
			if rel, ok := strings.CutPrefix(e.Path, folder+"/"); ok {
				e.Path = rel
				entries = append(entries, e)
			}
		}
	}
	if treeSHA != nil && *treeSHA != "" && resolved != *treeSHA {
		return api.GitHubFolder{}, &GitHubError{Msg: fmt.Sprintf("%s at %s is tree %s, not %s as the catalog pins it", where, commit, resolved, *treeSHA)}
	}
	if tree.Truncated {
		var sub apiTree
		if err := x.apiGet(ctx, token, base+"/git/trees/"+resolved+"?recursive=1", &sub); err != nil {
			return api.GitHubFolder{}, err
		}
		if sub.Truncated {
			return api.GitHubFolder{}, &GitHubError{Msg: where + " is too large to list"}
		}
		entries = sub.Tree
	}
	blobs, err := packageBlobs(entries, where)
	if err != nil {
		return api.GitHubFolder{}, err
	}
	raw := x.Fetch.GitHub.Raw + "/" + repo + "/" + commit + "/"
	if folder != "" {
		raw += (&url.URL{Path: folder}).EscapedPath() + "/"
	}
	files, err := x.rawFiles(ctx, token, raw, blobs, where, commit)
	if err != nil {
		return api.GitHubFolder{}, err
	}
	return api.GitHubFolder{Commit: commit, TreeSHA: resolved, Files: files}, nil
}

// packageBlobs is _package_blobs: the files a package takes, no links, submodules or hidden files.
func packageBlobs(entries []apiTreeEntry, where string) ([]apiTreeEntry, error) {
	var out []apiTreeEntry
	var total int64
	for _, e := range entries {
		if e.Type != "blob" && e.Type != "commit" {
			continue
		}
		hidden := false
		for _, p := range strings.Split(e.Path, "/") {
			hidden = hidden || strings.HasPrefix(p, ".")
		}
		if e.Type == "commit" || e.Mode == "120000" || hidden {
			continue
		}
		out = append(out, e)
		total += e.Size
		if len(out) > maxFolderFiles {
			return nil, &GitHubError{Msg: fmt.Sprintf("GitHub skill package contains more than %d files", maxFolderFiles)}
		}
		if total > maxFolderBytes {
			return nil, &GitHubError{Msg: fmt.Sprintf("GitHub skill package exceeds %d MB uncompressed limit", maxFolderBytes/(1024*1024))}
		}
	}
	if len(out) == 0 {
		return nil, &GitHubError{Msg: "No files found in " + where}
	}
	return out, nil
}

func (x Installs) rawFiles(ctx context.Context, token, base string, blobs []apiTreeEntry, where, commit string) (map[string][]byte, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	files := make(map[string][]byte, len(blobs))
	var mu sync.Mutex
	var first error
	var wg sync.WaitGroup
	slots := make(chan struct{}, folderDownloads)
	for _, b := range blobs {
		wg.Add(1)
		slots <- struct{}{}
		go func() {
			defer func() { <-slots; wg.Done() }()
			data, err := x.rawFile(ctx, token, base, b, where, commit)
			mu.Lock()
			defer mu.Unlock()
			if err != nil {
				if first == nil {
					first = err
					cancel()
				}
				return
			}
			files[b.Path] = data
		}()
	}
	wg.Wait()
	if first != nil {
		return nil, first
	}
	return files, nil
}

func (x Installs) rawFile(ctx context.Context, token, base string, b apiTreeEntry, where, commit string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+(&url.URL{Path: b.Path}).EscapedPath(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := x.Fetch.client(netguard.Vendor, githubTimeout, 10).Do(req)
	if err != nil {
		return nil, &GitHubError{Msg: fmt.Sprintf("Error reading %s of %s: %v", b.Path, where, err)}
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode == http.StatusNotFound {
		return nil, &GitHubError{Msg: fmt.Sprintf("The skill was removed upstream: %s of %s is gone", b.Path, where), Status: 404}
	}
	if err := apiCheck(resp); err != nil {
		return nil, err
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxFolderBytes+1))
	if err != nil {
		return nil, &GitHubError{Msg: fmt.Sprintf("Error reading %s of %s: %v", b.Path, where, err)}
	}
	if blobSHA(data) != b.SHA {
		return nil, &GitHubError{Msg: fmt.Sprintf("%s of %s at %s does not match its blob SHA", b.Path, where, commit)}
	}
	return data, nil
}
