package packageimage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

var ErrPackageNotFound = errors.New("package was not found")

// VersionResolver resolves a package invocation to an immutable release.
type VersionResolver struct {
	NPMRegistryURL string
	PyPIURL        string
	Client         *http.Client
}

func (r *VersionResolver) Resolve(ctx context.Context, invocation Invocation) (string, error) {
	if invocation.Version != "" && invocation.Version != "latest" {
		if err := r.checkExact(ctx, invocation); err != nil {
			return "", err
		}
		return invocation.Version, nil
	}
	if invocation.Ecosystem == EcosystemNPM {
		return r.resolveNPMLatest(ctx, invocation.Package)
	}
	return r.resolvePyPILatest(ctx, invocation.Package)
}

func (r *VersionResolver) checkExact(ctx context.Context, invocation Invocation) error {
	if invocation.Ecosystem == EcosystemNPM {
		var payload struct {
			Versions map[string]json.RawMessage `json:"versions"`
		}
		if err := r.getJSON(ctx, r.npmURL(invocation.Package), &payload); err != nil {
			return err
		}
		if _, ok := payload.Versions[invocation.Version]; !ok {
			return fmt.Errorf("%w: npm package %s version %s", ErrPackageNotFound, invocation.Package, invocation.Version)
		}
		return nil
	}
	var payload struct {
		Info struct {
			Version string `json:"version"`
		} `json:"info"`
	}
	if err := r.getJSON(ctx, r.pypiURL(invocation.Package, invocation.Version), &payload); err != nil {
		return err
	}
	if payload.Info.Version == "" || payload.Info.Version != invocation.Version {
		return fmt.Errorf("%w: PyPI package %s version %s", ErrPackageNotFound, invocation.Package, invocation.Version)
	}
	return nil
}

func (r *VersionResolver) resolveNPMLatest(ctx context.Context, packageName string) (string, error) {
	var payload struct {
		DistTags struct {
			Latest string `json:"latest"`
		} `json:"dist-tags"`
		Versions map[string]json.RawMessage `json:"versions"`
	}
	if err := r.getJSON(ctx, r.npmURL(packageName), &payload); err != nil {
		return "", err
	}
	if payload.DistTags.Latest == "" || !npmExactVersion.MatchString(payload.DistTags.Latest) {
		return "", fmt.Errorf("npm registry returned no exact latest version for %s", packageName)
	}
	if _, ok := payload.Versions[payload.DistTags.Latest]; !ok {
		return "", fmt.Errorf("npm registry latest version %s is not present for %s", payload.DistTags.Latest, packageName)
	}
	return payload.DistTags.Latest, nil
}

func (r *VersionResolver) resolvePyPILatest(ctx context.Context, packageName string) (string, error) {
	var payload struct {
		Info struct {
			Version string `json:"version"`
		} `json:"info"`
	}
	if err := r.getJSON(ctx, r.pypiURL(packageName, ""), &payload); err != nil {
		return "", err
	}
	if payload.Info.Version == "" || !pypiExactVersion.MatchString(payload.Info.Version) {
		return "", fmt.Errorf("PyPI registry returned no exact latest version for %s", packageName)
	}
	return payload.Info.Version, nil
}

func (r *VersionResolver) getJSON(ctx context.Context, endpoint string, out any) error {
	client := r.Client
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return fmt.Errorf("build package registry request: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("package registry request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound {
		return fmt.Errorf("%w: package registry returned 404", ErrPackageNotFound)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("package registry returned HTTP %d", response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 8<<20))
	if err != nil {
		return fmt.Errorf("read package registry response: %w", err)
	}
	if err := json.Unmarshal(body, out); err != nil {
		return fmt.Errorf("decode package registry response: %w", err)
	}
	return nil
}

func (r *VersionResolver) npmURL(packageName string) string {
	base := strings.TrimRight(r.NPMRegistryURL, "/")
	if base == "" {
		base = "https://registry.npmjs.org"
	}
	return base + "/" + strings.ReplaceAll(packageName, "/", "%2f")
}

func (r *VersionResolver) pypiURL(packageName, version string) string {
	base := strings.TrimRight(r.PyPIURL, "/")
	if base == "" {
		base = "https://pypi.org"
	}
	name := normalizePyPIName(packageName)
	if version == "" {
		return base + "/pypi/" + name + "/json"
	}
	return base + "/pypi/" + name + "/" + version + "/json"
}

var pypiNameSeparator = regexp.MustCompile(`[-_.]+`)

func normalizePyPIName(packageName string) string {
	return pypiNameSeparator.ReplaceAllString(strings.ToLower(strings.TrimSpace(packageName)), "-")
}
