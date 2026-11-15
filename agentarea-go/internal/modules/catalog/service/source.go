package service

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha1" //nolint:gosec // git object ids are SHA-1
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

// Fetch limits (service.py, github_client.py, github_git.py).
const (
	sourceFetchTimeout      = 30 * time.Second
	sourceDeadline          = 60 * time.Second
	maxSourceRedirects      = 5
	maxPlatformSourceBytes  = 64 * 1024 * 1024
	githubTimeout           = 30 * time.Second
	rawReadBytes            = 64 * 1024
	maxArchiveBytes         = 25 * 1024 * 1024
	maxArchiveUnpackedBytes = 256 * 1024 * 1024
	maxArchiveMembers       = 50_000
	maxArchiveSkillBytes    = 64 * 1024 * 1024
	maxLsRefsBytes          = 64 * 1024
	userAgent               = "agentarea-registry-sync"
)

// GitHubEndpoints are where GitHub is reached; tests point them at httptest servers.
type GitHubEndpoints struct {
	API, Raw, Git, Codeload string
}

// DefaultGitHub is github.com.
func DefaultGitHub() GitHubEndpoints {
	return GitHubEndpoints{API: "https://api.github.com", Raw: "https://raw.githubusercontent.com",
		Git: "https://github.com", Codeload: "https://codeload.github.com"}
}

// GitHubError is GitHubApiError / GitHubGitError: Status 0 when GitHub
// answered something unreadable.
type GitHubError struct {
	Msg       string
	Status    int
	RateLimit bool
}

func (e *GitHubError) Error() string { return e.Msg }

// Fetcher reads catalog sources through the module's outbound clients.
type Fetcher struct {
	Net    netguard.Clients
	GitHub GitHubEndpoints
}

func (f Fetcher) client(dest netguard.Destination, timeout time.Duration, redirects int) *http.Client {
	return &http.Client{Transport: f.Net.Transport(dest), Timeout: timeout,
		CheckRedirect: func(_ *http.Request, via []*http.Request) error {
			if len(via) > redirects {
				return errors.New("too many redirects")
			}
			return nil
		}}
}

// unreachable is a transport failure, classified for the registry's owner.
type unreachable struct{ err error }

func (e *unreachable) Error() string { return "the source could not be reached" }
func (e *unreachable) Unwrap() error { return e.err }

// httpStatus is a source's non-200 answer.
type httpStatus struct{ code int }

func (e *httpStatus) Error() string { return fmt.Sprintf("the source answered HTTP %d", e.code) }

func readCapped(r io.Reader, limit int, tooLarge error) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(r, int64(limit)+1))
	if err != nil {
		return nil, &unreachable{err}
	}
	if len(body) > limit {
		return nil, tooLarge
	}
	return body, nil
}

// PlatformEtag is _source_etag: nil for a local file or a host without one.
func (f Fetcher) PlatformEtag(ctx context.Context, src string) *string {
	if !strings.HasPrefix(src, "http://") && !strings.HasPrefix(src, "https://") {
		return nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodHead, src, nil)
	if err != nil {
		return nil
	}
	req.Header.Set("User-Agent", userAgent)
	resp, err := f.client(netguard.Vendor, sourceFetchTimeout, 10).Do(req)
	if err != nil {
		return nil
	}
	_ = resp.Body.Close()
	if resp.StatusCode >= 400 {
		return nil
	}
	if e := resp.Header.Get("ETag"); e != "" {
		return &e
	}
	return nil
}

// PlatformSource is _fetch_source: a URL or a local file, JSON else YAML.
func (f Fetcher) PlatformSource(ctx context.Context, src string) (any, error) {
	var body []byte
	if strings.HasPrefix(src, "http://") || strings.HasPrefix(src, "https://") {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, src, nil)
		if err != nil {
			return nil, &unreachable{err}
		}
		req.Header.Set("Accept", "application/json, application/yaml, text/yaml, */*")
		req.Header.Set("User-Agent", userAgent)
		resp, err := f.client(netguard.Vendor, sourceFetchTimeout, 10).Do(req)
		if err != nil {
			return nil, &unreachable{err}
		}
		defer func() { _ = resp.Body.Close() }()
		if resp.StatusCode != http.StatusOK {
			return nil, &httpStatus{resp.StatusCode}
		}
		if body, err = readCapped(resp.Body, maxPlatformSourceBytes, &SourceError{Msg: "the source is larger than " + size(maxPlatformSourceBytes)}); err != nil {
			return nil, err
		}
	} else {
		b, err := os.ReadFile(src) //nolint:gosec // the platform manifest names it
		if err != nil {
			return nil, &unreachable{err}
		}
		body = b
	}
	if v, err := DecodeJSON(body); err == nil {
		return v, nil
	}
	v, err := loadYAML(body, 10*MaxYAMLNodes)
	if err != nil {
		return nil, &SourceError{Msg: "the source is not a valid JSON or YAML index"}
	}
	return v, nil
}

func requireHTTPS(src string) error {
	u, err := url.Parse(src)
	if err != nil || u.Scheme != "https" {
		return &SourceError{Msg: "the source is not a public https URL"}
	}
	return nil
}

func (f Fetcher) memberRequest(ctx context.Context, method, src string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, src, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json, application/yaml, text/yaml")
	req.Header.Set("User-Agent", userAgent)
	return f.client(netguard.Member, sourceFetchTimeout, maxSourceRedirects).Do(req)
}

// WorkspaceEtag is _untrusted_etag: a 200 HEAD's ETag, else nil.
func (f Fetcher) WorkspaceEtag(ctx context.Context, src string) (*string, error) {
	if err := requireHTTPS(src); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, sourceDeadline)
	defer cancel()
	resp, err := f.memberRequest(ctx, http.MethodHead, src)
	if err != nil {
		return nil, nil
	}
	_ = resp.Body.Close()
	if e := resp.Header.Get("ETag"); resp.StatusCode == http.StatusOK && e != "" {
		return &e, nil
	}
	return nil, nil
}

// WorkspaceSource is _fetch_untrusted: https, 200, a body cap and a deadline.
func (f Fetcher) WorkspaceSource(ctx context.Context, src string) (any, error) {
	if err := requireHTTPS(src); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, sourceDeadline)
	defer cancel()
	resp, err := f.memberRequest(ctx, http.MethodGet, src)
	if err != nil {
		if ctx.Err() != nil {
			return nil, &SourceError{Msg: fmt.Sprintf("the source took longer than %g s to read", sourceDeadline.Seconds())}
		}
		return nil, &SourceError{Msg: "the source could not be reached"}
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, &SourceError{Msg: fmt.Sprintf("the source answered HTTP %d", resp.StatusCode)}
	}
	body, err := readCapped(resp.Body, MaxSourceBytes, &SourceError{Msg: "the source is larger than " + size(MaxSourceBytes)})
	if err != nil {
		var se *SourceError
		if errors.As(err, &se) {
			return nil, err
		}
		if ctx.Err() != nil {
			return nil, &SourceError{Msg: fmt.Sprintf("the source took longer than %g s to read", sourceDeadline.Seconds())}
		}
		return nil, &SourceError{Msg: "the source could not be reached"}
	}
	return ParseUntrusted(body)
}

// GitHubSource is the reads a skills registry sync makes of one repository.
type GitHubSource interface {
	Head(ctx context.Context, repo string, ref *string) (string, error)
	Tree(ctx context.Context, repo, commit string) (entries []TreeEntry, root string, truncated bool, err error)
	Raw(ctx context.Context, repo, commit, p string) ([]byte, error)
}

// TreeEntry is one entry of a recursive git tree.
type TreeEntry struct{ Path, Type, SHA string }

// Repo is github_source: the REST API with a token, the archive without.
func (f Fetcher) Repo(token string) GitHubSource {
	if token != "" {
		return &restGitHub{f: f, token: token, roots: map[string]string{}}
	}
	return &archiveGitHub{f: f, files: map[string]map[string]gitFile{}}
}

type restGitHub struct {
	f     Fetcher
	token string
	roots map[string]string
}

func (g *restGitHub) get(ctx context.Context, p string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, g.f.GitHub.API+p, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("Authorization", "Bearer "+g.token)
	resp, err := g.f.client(netguard.Vendor, githubTimeout, 10).Do(req)
	if err != nil {
		return &unreachable{err}
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return &GitHubError{Msg: fmt.Sprintf("GitHub %s answered %d", p, resp.StatusCode), Status: resp.StatusCode}
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 64*1024*1024)).Decode(out); err != nil {
		return &GitHubError{Msg: "GitHub returned something this sync cannot read"}
	}
	return nil
}

func (g *restGitHub) Head(ctx context.Context, repo string, ref *string) (string, error) {
	r := "HEAD"
	if ref != nil {
		r = *ref
	}
	var c struct {
		SHA    string `json:"sha"`
		Commit struct {
			Tree struct {
				SHA string `json:"sha"`
			} `json:"tree"`
		} `json:"commit"`
	}
	if err := g.get(ctx, "/repos/"+repo+"/commits/"+url.PathEscape(r), &c); err != nil {
		return "", err
	}
	g.roots[c.SHA] = c.Commit.Tree.SHA
	return c.SHA, nil
}

func (g *restGitHub) Tree(ctx context.Context, repo, commit string) ([]TreeEntry, string, bool, error) {
	tree := commit
	if r, ok := g.roots[commit]; ok {
		tree = r
	}
	var t struct {
		SHA       string      `json:"sha"`
		Truncated bool        `json:"truncated"`
		Tree      []TreeEntry `json:"tree"`
	}
	if err := g.get(ctx, "/repos/"+repo+"/git/trees/"+tree+"?recursive=1", &t); err != nil {
		return nil, "", false, err
	}
	return t.Tree, t.SHA, t.Truncated, nil
}

func (g *restGitHub) Raw(ctx context.Context, repo, commit, p string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, g.f.GitHub.Raw+"/"+repo+"/"+commit+"/"+(&url.URL{Path: p}).EscapedPath(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Authorization", "Bearer "+g.token)
	resp, err := g.f.client(netguard.Vendor, githubTimeout, 10).Do(req)
	if err != nil {
		return nil, &unreachable{err}
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, &GitHubError{Msg: fmt.Sprintf("GitHub raw %s/%s answered %d", repo, p, resp.StatusCode), Status: resp.StatusCode}
	}
	body, _ := io.ReadAll(io.LimitReader(resp.Body, rawReadBytes))
	return body, nil
}

func (e *TreeEntry) UnmarshalJSON(b []byte) error {
	var v struct{ Path, Type, SHA string }
	if err := json.Unmarshal(b, &v); err != nil {
		return err
	}
	*e = TreeEntry(v)
	return nil
}

type gitFile struct {
	mode, sha string
	data      []byte
}

type archiveGitHub struct {
	f     Fetcher
	files map[string]map[string]gitFile
}

var repoPart = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)

func checkedRepo(repo string) error {
	parts := strings.Split(repo, "/")
	if len(parts) != 2 {
		return &GitHubError{Msg: "Not a GitHub repository name: " + PyRepr(repo)}
	}
	for _, p := range parts {
		if !repoPart.MatchString(p) || p == "." || p == ".." {
			return &GitHubError{Msg: "Not a GitHub repository name: " + PyRepr(repo)}
		}
	}
	return nil
}

func gitCheck(resp *http.Response, what string) error {
	switch {
	case resp.StatusCode == http.StatusOK:
		return nil
	case resp.StatusCode == http.StatusTooManyRequests || (resp.StatusCode == http.StatusForbidden && resp.Header.Get("Retry-After") != ""):
		return &GitHubError{Msg: "GitHub throttled " + what + "; retry later", Status: 429, RateLimit: true}
	case resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusNotFound:
		return &GitHubError{Msg: what + ": not on GitHub, or private", Status: 404}
	}
	return &GitHubError{Msg: fmt.Sprintf("%s: GitHub answered %d", what, resp.StatusCode)}
}

func pkt(line string) string { return fmt.Sprintf("%04x", len(line)+4) + line }

// ResolveCommit is github_git.resolve_commit over git smart HTTP (protocol v2 ls-refs).
func (f Fetcher) ResolveCommit(ctx context.Context, repo string, ref *string) (string, error) {
	if err := checkedRepo(repo); err != nil {
		return "", err
	}
	if ref != nil && gitSHA.MatchString(*ref) {
		return *ref, nil
	}
	wanted := []string{"HEAD"}
	if ref != nil {
		if *ref == "" || strings.ContainsFunc(*ref, func(r rune) bool { return r <= ' ' }) {
			return "", &GitHubError{Msg: "Not a git ref: " + PyRepr(*ref)}
		}
		if strings.HasPrefix(*ref, "refs/") {
			wanted = []string{*ref}
		} else {
			wanted = []string{"refs/heads/" + *ref, "refs/tags/" + *ref}
		}
	}
	body := pkt("command=ls-refs\n") + pkt("agent=agentarea\n") + "0001" + pkt("peel\n") + pkt("symrefs\n")
	for _, w := range wanted {
		body += pkt("ref-prefix " + w + "\n")
	}
	body += "0000"
	what := repo + " ref HEAD"
	if ref != nil {
		what = repo + " ref " + *ref
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, f.GitHub.Git+"/"+repo+".git/git-upload-pack", strings.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-git-upload-pack-request")
	req.Header.Set("Accept", "application/x-git-upload-pack-result")
	req.Header.Set("Git-Protocol", "version=2")
	req.Header.Set("User-Agent", "git/2 agentarea")
	resp, err := f.client(netguard.Vendor, 60*time.Second, 10).Do(req)
	if err != nil {
		return "", &GitHubError{Msg: what + ": " + err.Error()}
	}
	defer func() { _ = resp.Body.Close() }()
	if err := gitCheck(resp, what); err != nil {
		return "", err
	}
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, maxLsRefsBytes+1))
	if len(raw) > maxLsRefsBytes {
		return "", &GitHubError{Msg: what + ": GitHub answered more refs than asked for"}
	}
	found := map[string]string{}
	for at := 0; at+4 <= len(raw); {
		n, err := strconv.ParseUint(string(raw[at:at+4]), 16, 16)
		if err != nil {
			return "", &GitHubError{Msg: "GitHub answered something that is not a git response"}
		}
		if n < 4 {
			at += 4
			continue
		}
		end := min(at+int(n), len(raw))
		fields := strings.Split(strings.TrimRight(string(raw[at+4:end]), "\n"), " ")
		at = end
		if len(fields) < 2 || !gitSHA.MatchString(fields[0]) {
			continue
		}
		sha := fields[0]
		for _, fl := range fields[2:] {
			if p, ok := strings.CutPrefix(fl, "peeled:"); ok && gitSHA.MatchString(p) {
				sha = p
			}
		}
		found[fields[1]] = sha
	}
	for _, w := range wanted {
		if s, ok := found[w]; ok {
			return s, nil
		}
	}
	r := "None"
	if ref != nil {
		r = PyRepr(*ref)
	}
	return "", &GitHubError{Msg: repo + " has no branch or tag " + r, Status: 404}
}

// readArchive is github_git.read_archive: every file hashed, keep's bytes kept.
func (f Fetcher) readArchive(ctx context.Context, repo, commit string, keep func(p, mode string) bool, maxKept int) (map[string]gitFile, error) {
	if err := checkedRepo(repo); err != nil {
		return nil, err
	}
	if !gitSHA.MatchString(commit) {
		return nil, &GitHubError{Msg: "Not a commit: " + PyRepr(commit)}
	}
	what := repo + " at " + commit
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, f.GitHub.Codeload+"/"+repo+"/tar.gz/"+commit, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "agentarea")
	resp, err := f.client(netguard.Vendor, 60*time.Second, 10).Do(req)
	if err != nil {
		return nil, &GitHubError{Msg: what + ": " + err.Error()}
	}
	defer func() { _ = resp.Body.Close() }()
	if err := gitCheck(resp, what); err != nil {
		return nil, err
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxArchiveBytes+1))
	if err != nil {
		return nil, &GitHubError{Msg: what + ": " + err.Error()}
	}
	if len(data) > maxArchiveBytes {
		return nil, &GitHubError{Msg: fmt.Sprintf("%s is larger than %d MB compressed", what, maxArchiveBytes/(1024*1024))}
	}
	return unpack(data, keep, maxKept, what)
}

func blobSHA(data []byte) string {
	h := sha1.New() //nolint:gosec // git object id
	h.Write([]byte("blob " + strconv.Itoa(len(data)) + "\x00"))
	h.Write(data)
	return hex.EncodeToString(h.Sum(nil))
}

func unpack(data []byte, keep func(p, mode string) bool, maxKept int, what string) (map[string]gitFile, error) {
	unreadable := func(err error) error {
		return &GitHubError{Msg: what + ": the archive is not readable (" + err.Error() + ")"}
	}
	zr, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, unreadable(err)
	}
	tr := tar.NewReader(zr)
	files := map[string]gitFile{}
	root := ""
	kept, unpacked, members := 0, int64(0), 0
	for {
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, unreadable(err)
		}
		if h.Typeflag == tar.TypeXGlobalHeader {
			continue
		}
		members++
		if members > maxArchiveMembers {
			return nil, &GitHubError{Msg: fmt.Sprintf("%s holds more than %d entries", what, maxArchiveMembers)}
		}
		isFile := h.Typeflag == tar.TypeReg
		if isFile {
			unpacked += h.Size
			if unpacked > maxArchiveUnpackedBytes {
				return nil, &GitHubError{Msg: what + " unpacks to too much"}
			}
		}
		if root == "" {
			root = strings.SplitN(h.Name, "/", 2)[0] + "/"
		}
		rel, ok := strings.CutPrefix(h.Name, root)
		if !ok || (!isFile && h.Typeflag != tar.TypeSymlink) {
			continue
		}
		var content []byte
		mode := "100644"
		if h.Typeflag == tar.TypeSymlink {
			content, mode = []byte(h.Linkname), "120000"
		} else {
			if content, err = io.ReadAll(tr); err != nil {
				return nil, unreadable(err)
			}
			if h.Mode&0o111 != 0 {
				mode = "100755"
			}
		}
		gf := gitFile{mode: mode, sha: blobSHA(content)}
		if keep(rel, mode) {
			kept += len(content)
			if kept > maxKept {
				return nil, &GitHubError{Msg: fmt.Sprintf("%s holds more than %d MB under /", what, maxKept/(1024*1024))}
			}
			gf.data = content
		}
		files[rel] = gf
	}
	return files, nil
}

// gitTreeSHAs is git_tree_shas: the tree id of every folder ("" the root).
func gitTreeSHAs(files map[string]gitFile) map[string]string {
	type child struct{ mode, sha string }
	children := map[string]map[string]child{"": {}}
	for p, f := range files {
		parts := strings.Split(p, "/")
		for d := 0; d < len(parts)-1; d++ {
			parent, dir := strings.Join(parts[:d], "/"), strings.Join(parts[:d+1], "/")
			if children[parent] == nil {
				children[parent] = map[string]child{}
			}
			children[parent][parts[d]] = child{mode: "40000"}
			if children[dir] == nil {
				children[dir] = map[string]child{}
			}
		}
		dir := strings.Join(parts[:len(parts)-1], "/")
		if children[dir] == nil {
			children[dir] = map[string]child{}
		}
		children[dir][parts[len(parts)-1]] = child{mode: f.mode, sha: f.sha}
	}
	dirs := make([]string, 0, len(children))
	for d := range children {
		dirs = append(dirs, d)
	}
	depth := func(d string) int {
		if d == "" {
			return 0
		}
		return strings.Count(d, "/") + 1
	}
	sort.SliceStable(dirs, func(i, j int) bool { return depth(dirs[i]) > depth(dirs[j]) })
	shas := map[string]string{}
	for _, d := range dirs {
		entries := children[d]
		names := make([]string, 0, len(entries))
		for n := range entries {
			names = append(names, n)
		}
		key := func(n string) string {
			if entries[n].mode == "40000" {
				return n + "/"
			}
			return n
		}
		sort.Slice(names, func(i, j int) bool { return key(names[i]) < key(names[j]) })
		var body bytes.Buffer
		for _, n := range names {
			c := entries[n]
			sha := c.sha
			if sha == "" {
				sha = shas[path.Join(d, n)]
			}
			raw, _ := hex.DecodeString(sha)
			body.WriteString(c.mode + " " + n + "\x00")
			body.Write(raw)
		}
		h := sha1.New() //nolint:gosec // git object id
		h.Write([]byte("tree " + strconv.Itoa(body.Len()) + "\x00"))
		h.Write(body.Bytes())
		shas[d] = hex.EncodeToString(h.Sum(nil))
	}
	return shas
}

func (g *archiveGitHub) Head(ctx context.Context, repo string, ref *string) (string, error) {
	return g.f.ResolveCommit(ctx, repo, ref)
}

func (g *archiveGitHub) snapshot(ctx context.Context, repo, commit string) (map[string]gitFile, error) {
	key := repo + "@" + commit
	if fs, ok := g.files[key]; ok {
		return fs, nil
	}
	fs, err := g.f.readArchive(ctx, repo, commit, func(p, mode string) bool {
		return path.Base(p) == skillFile && mode != "120000"
	}, maxArchiveSkillBytes)
	if err != nil {
		return nil, err
	}
	g.files[key] = fs
	return fs, nil
}

func (g *archiveGitHub) Tree(ctx context.Context, repo, commit string) ([]TreeEntry, string, bool, error) {
	fs, err := g.snapshot(ctx, repo, commit)
	if err != nil {
		return nil, "", false, err
	}
	trees := gitTreeSHAs(fs)
	var out []TreeEntry
	for p, f := range fs {
		out = append(out, TreeEntry{Path: p, Type: "blob", SHA: f.sha})
	}
	for p, sha := range trees {
		if p != "" {
			out = append(out, TreeEntry{Path: p, Type: "tree", SHA: sha})
		}
	}
	return out, trees[""], false, nil
}

func (g *archiveGitHub) Raw(ctx context.Context, repo, commit, p string) ([]byte, error) {
	fs, err := g.snapshot(ctx, repo, commit)
	if err != nil {
		return nil, err
	}
	f, ok := fs[p]
	if !ok || f.data == nil {
		return nil, &GitHubError{Msg: repo + "/" + p + " is not in the archive of " + commit, Status: 404}
	}
	if len(f.data) > rawReadBytes {
		return f.data[:rawReadBytes], nil
	}
	return f.data, nil
}

// PointerTrees is the tree a GitHub pointer's folder is now, token-free;
// one per run of checks.
type PointerTrees struct {
	f       Fetcher
	commits map[string]string
	trees   map[string]map[string]string
}

// NewPointerTrees starts a run of pointer checks.
func (f Fetcher) NewPointerTrees() *PointerTrees {
	return &PointerTrees{f: f, commits: map[string]string{}, trees: map[string]map[string]string{}}
}

// Tree is PointerTrees.__call__.
func (p *PointerTrees) Tree(ctx context.Context, source map[string]any) (string, error) {
	repo := fmt.Sprint(source["repo"])
	folder := strings.Trim(fmt.Sprint(or(source["path"], "")), "/")
	ref := optStr(source["ref"])
	key := repo + "#"
	if ref != nil {
		key += *ref
	}
	commit, ok := p.commits[key]
	if !ok {
		c, err := p.f.ResolveCommit(ctx, repo, ref)
		if err != nil {
			return "", err
		}
		commit, p.commits[key] = c, c
	}
	trees, ok := p.trees[repo+"@"+commit]
	if !ok {
		fs, err := p.f.readArchive(ctx, repo, commit, func(string, string) bool { return false }, 0)
		if err != nil {
			return "", err
		}
		trees = gitTreeSHAs(fs)
		p.trees[repo+"@"+commit] = trees
	}
	t, ok := trees[folder]
	if !ok {
		return "", &GitHubError{Msg: fmt.Sprintf("%s/%s is not in %s at %s", repo, folder, repo, commit), Status: 404}
	}
	return t, nil
}
