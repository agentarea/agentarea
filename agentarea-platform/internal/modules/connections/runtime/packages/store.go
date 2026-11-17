package packages

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"

	"github.com/google/go-containerregistry/pkg/authn"
	"github.com/google/go-containerregistry/pkg/name"
	v1 "github.com/google/go-containerregistry/pkg/v1"
	"github.com/google/go-containerregistry/pkg/v1/remote"
	"github.com/google/go-containerregistry/pkg/v1/remote/transport"
	"github.com/google/go-containerregistry/pkg/v1/tarball"
)

// ErrImageNotFound is a package image the store does not hold yet.
var ErrImageNotFound = errors.New("package image not found")

const entrypointLabel = "io.agentarea.mcp.entrypoint"

// StoredImage is a previously assembled package image.
type StoredImage struct {
	Ref        string
	Digest     string
	Entrypoint []string
}

// ImageStore persists immutable package images and supplies the base image.
type ImageStore interface {
	Lookup(ctx context.Context, pkg Package) (StoredImage, error)
	Base(ctx context.Context, ref string) (v1.Image, error)
	Put(ctx context.Context, pkg Package, entrypoint []string, image v1.Image) (StoredImage, error)
}

// RegistryStore stores package images in an OCI registry repository.
type RegistryStore struct {
	repository string
	keychain   authn.Keychain
	transport  http.RoundTripper
}

// NewRegistryStore pushes under repository, reaching registries over rt.
func NewRegistryStore(repository string, rt http.RoundTripper) *RegistryStore {
	return &RegistryStore{repository: strings.TrimRight(repository, "/"), keychain: authn.DefaultKeychain, transport: rt}
}

func (s *RegistryStore) Lookup(ctx context.Context, pkg Package) (StoredImage, error) {
	tag, err := s.tagReference(pkg)
	if err != nil {
		return StoredImage{}, err
	}
	descriptor, err := remote.Head(tag, s.options(ctx)...)
	if err != nil {
		if registryNotFound(err) {
			return StoredImage{}, ErrImageNotFound
		}
		return StoredImage{}, fmt.Errorf("look up package image %s: %w", tag, err)
	}
	image, err := remote.Image(tag, s.options(ctx)...)
	if err != nil {
		return StoredImage{}, fmt.Errorf("read package image %s: %w", tag, err)
	}
	entrypoint, err := imageEntrypoint(image)
	if err != nil {
		return StoredImage{}, err
	}
	digest := descriptor.Digest.String()
	return StoredImage{Ref: s.repositoryPath(pkg) + "@" + digest, Digest: digest, Entrypoint: entrypoint}, nil
}

func (s *RegistryStore) Base(ctx context.Context, ref string) (v1.Image, error) {
	base, err := name.ParseReference(ref)
	if err != nil {
		return nil, fmt.Errorf("parse base image %q: %w", ref, err)
	}
	image, err := remote.Image(base, s.options(ctx)...)
	if err != nil {
		return nil, fmt.Errorf("read base image %s: %w", base, err)
	}
	return image, nil
}

func (s *RegistryStore) Put(ctx context.Context, pkg Package, entrypoint []string, image v1.Image) (StoredImage, error) {
	tag, err := s.tagReference(pkg)
	if err != nil {
		return StoredImage{}, err
	}
	if err := remote.Write(tag, image, s.options(ctx)...); err != nil {
		return StoredImage{}, fmt.Errorf("push package image %s: %w", tag, err)
	}
	digest, err := image.Digest()
	if err != nil {
		return StoredImage{}, fmt.Errorf("calculate package image digest: %w", err)
	}
	return StoredImage{Ref: s.repositoryPath(pkg) + "@" + digest.String(), Digest: digest.String(), Entrypoint: append([]string(nil), entrypoint...)}, nil
}

func (s *RegistryStore) tagReference(pkg Package) (name.Tag, error) {
	return name.NewTag(s.repositoryPath(pkg)+":"+ImageTag(pkg.Version), name.WeakValidation)
}

func (s *RegistryStore) repositoryPath(pkg Package) string {
	return s.repository + "/" + RepositoryPath(pkg.Ecosystem, pkg.Name)
}

func (s *RegistryStore) options(ctx context.Context) []remote.Option {
	return []remote.Option{remote.WithContext(ctx), remote.WithAuthFromKeychain(s.keychain), remote.WithTransport(s.transport)}
}

// LocalStore keeps package images in the docker or podman image store the
// local backend runs from.
type LocalStore struct {
	runtime string

	// An image read from a `docker save` tarball reads its layers lazily, so
	// the file outlives every import using it; it is replaced when the base changes.
	baseMu   sync.Mutex
	baseID   string
	basePath string
}

// NewLocalStore drives the runtime CLI (docker or podman).
func NewLocalStore(runtime string) *LocalStore {
	return &LocalStore{runtime: runtime}
}

func (s *LocalStore) Lookup(ctx context.Context, pkg Package) (StoredImage, error) {
	inspection, err := s.inspect(ctx, s.tagReference(pkg))
	if err != nil {
		return StoredImage{}, err
	}
	entrypoint, err := parseEntrypointLabel(inspection.Config.Labels)
	if err != nil {
		return StoredImage{}, fmt.Errorf("read package image entrypoint: %w", err)
	}
	return StoredImage{Ref: inspection.ID, Digest: inspection.ID, Entrypoint: entrypoint}, nil
}

func (s *LocalStore) Base(ctx context.Context, ref string) (v1.Image, error) {
	inspection, err := s.inspect(ctx, ref)
	if errors.Is(err, ErrImageNotFound) {
		pull := exec.CommandContext(ctx, s.runtime, "pull", "--quiet", ref)
		if output, pullErr := pull.CombinedOutput(); pullErr != nil {
			return nil, fmt.Errorf("pull base image %s: %w (%s)", ref, pullErr, strings.TrimSpace(string(output)))
		}
		inspection, err = s.inspect(ctx, ref)
	}
	if err != nil {
		return nil, fmt.Errorf("inspect base image %s: %w", ref, err)
	}
	s.baseMu.Lock()
	defer s.baseMu.Unlock()
	if s.baseID != inspection.ID {
		path, err := s.saveBase(ctx, ref)
		if err != nil {
			return nil, err
		}
		if s.basePath != "" {
			if err := os.Remove(s.basePath); err != nil && !errors.Is(err, os.ErrNotExist) {
				return nil, fmt.Errorf("remove previous base tarball: %w", err)
			}
		}
		s.baseID, s.basePath = inspection.ID, path
	}
	image, err := tarball.ImageFromPath(s.basePath, nil)
	if err != nil {
		return nil, fmt.Errorf("read base tarball: %w", err)
	}
	return image, nil
}

func (s *LocalStore) saveBase(ctx context.Context, ref string) (string, error) {
	file, err := os.CreateTemp("", "mcp-package-base-*.tar")
	if err != nil {
		return "", fmt.Errorf("create base tarball: %w", err)
	}
	path := file.Name()
	var stderr strings.Builder
	command := exec.CommandContext(ctx, s.runtime, "save", ref)
	command.Stdout = file
	command.Stderr = &stderr
	runErr := command.Run()
	closeErr := file.Close()
	if err := errors.Join(runErr, closeErr); err != nil {
		return "", errors.Join(fmt.Errorf("save base image %s: %w (%s)", ref, err, strings.TrimSpace(stderr.String())), removeFile(path))
	}
	return path, nil
}

func (s *LocalStore) Put(ctx context.Context, pkg Package, entrypoint []string, image v1.Image) (stored StoredImage, err error) {
	ref := s.tagReference(pkg)
	tag, err := name.NewTag(ref, name.WeakValidation)
	if err != nil {
		return StoredImage{}, fmt.Errorf("parse local package image tag: %w", err)
	}
	file, err := os.CreateTemp("", "mcp-package-image-*.tar")
	if err != nil {
		return StoredImage{}, fmt.Errorf("create package image tarball: %w", err)
	}
	path := file.Name()
	defer func() { err = errors.Join(err, removeFile(path)) }()
	if err := tarball.Write(tag, image, file); err != nil {
		return StoredImage{}, errors.Join(fmt.Errorf("write package image tarball: %w", err), file.Close())
	}
	if err := file.Close(); err != nil {
		return StoredImage{}, fmt.Errorf("close package image tarball: %w", err)
	}
	input, err := os.Open(path) //nolint:gosec // path is the temp file created above
	if err != nil {
		return StoredImage{}, fmt.Errorf("open package image tarball: %w", err)
	}
	command := exec.CommandContext(ctx, s.runtime, "load")
	command.Stdin = input
	output, runErr := command.CombinedOutput()
	closeErr := input.Close()
	if runErr != nil {
		return StoredImage{}, fmt.Errorf("load package image %s: %w (%s)", ref, runErr, strings.TrimSpace(string(output)))
	}
	if closeErr != nil {
		return StoredImage{}, fmt.Errorf("close package image tarball: %w", closeErr)
	}
	inspection, err := s.inspect(ctx, ref)
	if err != nil {
		return StoredImage{}, fmt.Errorf("inspect loaded package image %s: %w", ref, err)
	}
	return StoredImage{Ref: inspection.ID, Digest: inspection.ID, Entrypoint: append([]string(nil), entrypoint...)}, nil
}

type dockerInspection struct {
	ID     string `json:"Id"`
	Config struct {
		Labels map[string]string `json:"Labels"`
	} `json:"Config"`
}

func (s *LocalStore) inspect(ctx context.Context, reference string) (dockerInspection, error) {
	var stderr strings.Builder
	command := exec.CommandContext(ctx, s.runtime, "image", "inspect", "--format", "{{json .}}", reference)
	command.Stderr = &stderr
	output, err := command.Output()
	if err != nil {
		if localImageMissing(stderr.String()) {
			return dockerInspection{}, ErrImageNotFound
		}
		return dockerInspection{}, fmt.Errorf("%s image inspect %s: %w (%s)", s.runtime, reference, err, strings.TrimSpace(stderr.String()))
	}
	var inspection dockerInspection
	if err := json.Unmarshal(output, &inspection); err != nil {
		return dockerInspection{}, fmt.Errorf("decode image inspect: %w", err)
	}
	if inspection.ID == "" {
		return dockerInspection{}, errors.New("image inspect returned no image id")
	}
	return inspection, nil
}

func (s *LocalStore) tagReference(pkg Package) string {
	return "agentarea-mcp-packages/" + RepositoryPath(pkg.Ecosystem, pkg.Name) + ":" + ImageTag(pkg.Version)
}

func localImageMissing(stderr string) bool {
	lower := strings.ToLower(stderr)
	return strings.Contains(lower, "no such image") || strings.Contains(lower, "image not known") || strings.Contains(lower, "failed to find image")
}

func imageEntrypoint(image v1.Image) ([]string, error) {
	config, err := image.ConfigFile()
	if err != nil {
		return nil, fmt.Errorf("read package image config: %w", err)
	}
	return parseEntrypointLabel(config.Config.Labels)
}

func parseEntrypointLabel(labels map[string]string) ([]string, error) {
	value := labels[entrypointLabel]
	if value == "" {
		return nil, errors.New("package image is missing " + entrypointLabel + " label")
	}
	var entrypoint []string
	if err := json.Unmarshal([]byte(value), &entrypoint); err != nil || len(entrypoint) == 0 {
		return nil, errors.New("package image has invalid " + entrypointLabel + " label")
	}
	return entrypoint, nil
}

func registryNotFound(err error) bool {
	var transportErr *transport.Error
	return errors.As(err, &transportErr) && transportErr.StatusCode == http.StatusNotFound
}

func removeFile(path string) error {
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("remove %s: %w", path, err)
	}
	return nil
}
