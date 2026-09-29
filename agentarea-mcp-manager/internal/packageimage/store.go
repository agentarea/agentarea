package packageimage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"

	"github.com/agentarea/mcp-manager/internal/mcpbase"
	"github.com/google/go-containerregistry/pkg/authn"
	"github.com/google/go-containerregistry/pkg/name"
	"github.com/google/go-containerregistry/pkg/v1"
	"github.com/google/go-containerregistry/pkg/v1/remote"
	"github.com/google/go-containerregistry/pkg/v1/remote/transport"
	"github.com/google/go-containerregistry/pkg/v1/tarball"
)

var ErrImageNotFound = errors.New("package image not found")

// StoredImage is a previously assembled package image.
type StoredImage struct {
	Ref        string
	Digest     string
	Entrypoint []string
}

// ImageStore persists immutable package images and supplies the mcp-base image.
type ImageStore interface {
	Lookup(context.Context, Package) (*StoredImage, error)
	Base(context.Context) (v1.Image, error)
	Put(context.Context, Package, []string, v1.Image) (*StoredImage, error)
}

// RegistryStore stores package images in an OCI/Docker registry.
type RegistryStore struct {
	repository string
	baseImage  string
	keychain   authn.Keychain
}

func NewRegistryStore(repository string) *RegistryStore {
	return &RegistryStore{repository: strings.TrimRight(repository, "/"), baseImage: mcpbase.Image(), keychain: authn.DefaultKeychain}
}

func (s *RegistryStore) Lookup(ctx context.Context, packageInfo Package) (*StoredImage, error) {
	tag, err := s.tagReference(packageInfo)
	if err != nil {
		return nil, err
	}
	descriptor, err := remote.Head(tag, s.options(ctx)...)
	if err != nil {
		if registryNotFound(err) {
			return nil, ErrImageNotFound
		}
		return nil, fmt.Errorf("look up package image %s: %w", tag, err)
	}
	image, err := remote.Image(tag, s.options(ctx)...)
	if err != nil {
		return nil, fmt.Errorf("read package image %s: %w", tag, err)
	}
	entrypoint, err := imageEntrypoint(image)
	if err != nil {
		return nil, err
	}
	return &StoredImage{Ref: immutableReference(s.repositoryPath(packageInfo), descriptor.Digest.String()), Digest: descriptor.Digest.String(), Entrypoint: entrypoint}, nil
}

func (s *RegistryStore) Base(ctx context.Context) (v1.Image, error) {
	base, err := name.ParseReference(s.baseImage)
	if err != nil {
		return nil, fmt.Errorf("parse mcp-base image %q: %w", s.baseImage, err)
	}
	image, err := remote.Image(base, s.options(ctx)...)
	if err != nil {
		return nil, fmt.Errorf("read mcp-base image %s: %w", base, err)
	}
	return image, nil
}

func (s *RegistryStore) Put(ctx context.Context, packageInfo Package, entrypoint []string, image v1.Image) (*StoredImage, error) {
	tag, err := s.tagReference(packageInfo)
	if err != nil {
		return nil, err
	}
	if err := remote.Write(tag, image, s.options(ctx)...); err != nil {
		return nil, fmt.Errorf("push package image %s: %w", tag, err)
	}
	digest, err := image.Digest()
	if err != nil {
		return nil, fmt.Errorf("calculate package image digest: %w", err)
	}
	return &StoredImage{Ref: immutableReference(s.repositoryPath(packageInfo), digest.String()), Digest: digest.String(), Entrypoint: append([]string(nil), entrypoint...)}, nil
}

func (s *RegistryStore) tagReference(packageInfo Package) (name.Tag, error) {
	return name.NewTag(s.repositoryPath(packageInfo)+":"+ImageTag(packageInfo.Version), name.WeakValidation)
}

func (s *RegistryStore) repositoryPath(packageInfo Package) string {
	return s.repository + "/" + RepositoryPath(packageInfo.Ecosystem, packageInfo.Name)
}

func (s *RegistryStore) options(ctx context.Context) []remote.Option {
	return []remote.Option{remote.WithContext(ctx), remote.WithAuthFromKeychain(s.keychain)}
}

// LocalStore uses the Docker-compatible CLI and image store.
type LocalStore struct {
	runtime   string
	baseImage string

	// A v1.Image read from a `docker save` tarball reads its layers from the
	// file lazily, so the file has to outlive every import that uses it. It
	// is kept per base image id and replaced when the base changes.
	baseMu   sync.Mutex
	baseID   string
	basePath string
}

func NewLocalStore(runtime string) *LocalStore {
	if strings.TrimSpace(runtime) == "" {
		runtime = "docker"
	}
	return &LocalStore{runtime: runtime, baseImage: mcpbase.Image()}
}

func (s *LocalStore) Lookup(ctx context.Context, packageInfo Package) (*StoredImage, error) {
	ref := s.tagReference(packageInfo)
	inspection, err := s.inspect(ctx, ref)
	if err != nil {
		return nil, ErrImageNotFound
	}
	entrypoint, err := parseEntrypointLabel(inspection.Config.Labels)
	if err != nil {
		return nil, fmt.Errorf("read package image entrypoint: %w", err)
	}
	return &StoredImage{Ref: inspection.ID, Digest: inspection.ID, Entrypoint: entrypoint}, nil
}

func (s *LocalStore) Base(ctx context.Context) (v1.Image, error) {
	inspection, err := s.inspect(ctx, s.baseImage)
	if err != nil {
		pull := exec.CommandContext(ctx, s.runtime, "pull", "--quiet", s.baseImage)
		if output, pullErr := pull.CombinedOutput(); pullErr != nil {
			return nil, fmt.Errorf("pull mcp-base image %s: %w (%s)", s.baseImage, pullErr, strings.TrimSpace(string(output)))
		}
		if inspection, err = s.inspect(ctx, s.baseImage); err != nil {
			return nil, fmt.Errorf("inspect mcp-base image %s: %w", s.baseImage, err)
		}
	}
	s.baseMu.Lock()
	defer s.baseMu.Unlock()
	if s.baseID != inspection.ID {
		path, err := s.saveBase(ctx)
		if err != nil {
			return nil, err
		}
		if s.basePath != "" {
			os.Remove(s.basePath)
		}
		s.baseID, s.basePath = inspection.ID, path
	}
	// `docker save` of one reference holds exactly one image, so no tag is
	// needed to pick it.
	image, err := tarball.ImageFromPath(s.basePath, nil)
	if err != nil {
		return nil, fmt.Errorf("read mcp-base tarball: %w", err)
	}
	return image, nil
}

func (s *LocalStore) saveBase(ctx context.Context) (string, error) {
	file, err := os.CreateTemp(os.TempDir(), "mcp-package-base-*.tar")
	if err != nil {
		return "", fmt.Errorf("create mcp-base tarball: %w", err)
	}
	path := file.Name()
	var stderr strings.Builder
	command := exec.CommandContext(ctx, s.runtime, "save", s.baseImage)
	command.Stdout = file
	command.Stderr = &stderr
	runErr := command.Run()
	closeErr := file.Close()
	if runErr != nil || closeErr != nil {
		os.Remove(path)
		return "", fmt.Errorf("save mcp-base image %s: %w (%s)", s.baseImage, errors.Join(runErr, closeErr), strings.TrimSpace(stderr.String()))
	}
	return path, nil
}

func (s *LocalStore) Put(ctx context.Context, packageInfo Package, entrypoint []string, image v1.Image) (*StoredImage, error) {
	ref := s.tagReference(packageInfo)
	file, err := os.CreateTemp(os.TempDir(), "mcp-package-image-*.tar")
	if err != nil {
		return nil, fmt.Errorf("create package image tarball: %w", err)
	}
	path := file.Name()
	tag, err := name.NewTag(ref, name.WeakValidation)
	if err != nil {
		return nil, fmt.Errorf("parse local package image tag: %w", err)
	}
	if err := tarball.Write(tag, image, file); err != nil {
		file.Close()
		os.Remove(path)
		return nil, fmt.Errorf("write package image tarball: %w", err)
	}
	if err := file.Close(); err != nil {
		os.Remove(path)
		return nil, fmt.Errorf("close package image tarball: %w", err)
	}
	defer os.Remove(path)
	input, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open package image tarball: %w", err)
	}
	command := exec.CommandContext(ctx, s.runtime, "load")
	command.Stdin = input
	output, runErr := command.CombinedOutput()
	closeErr := input.Close()
	if runErr != nil {
		return nil, fmt.Errorf("load package image %s: %w (%s)", ref, runErr, strings.TrimSpace(string(output)))
	}
	if closeErr != nil {
		return nil, fmt.Errorf("close package image tarball: %w", closeErr)
	}
	inspection, err := s.inspect(ctx, ref)
	if err != nil {
		return nil, fmt.Errorf("inspect loaded package image %s: %w", ref, err)
	}
	return &StoredImage{Ref: inspection.ID, Digest: inspection.ID, Entrypoint: append([]string(nil), entrypoint...)}, nil
}

type dockerInspection struct {
	ID     string `json:"Id"`
	Config struct {
		Labels map[string]string `json:"Labels"`
	} `json:"Config"`
}

func (s *LocalStore) inspect(ctx context.Context, reference string) (*dockerInspection, error) {
	command := exec.CommandContext(ctx, s.runtime, "image", "inspect", "--format", "{{json .}}", reference)
	output, err := command.Output()
	if err != nil {
		return nil, err
	}
	var inspection dockerInspection
	if err := json.Unmarshal(output, &inspection); err != nil {
		return nil, fmt.Errorf("decode Docker image inspect: %w", err)
	}
	if inspection.ID == "" {
		return nil, fmt.Errorf("Docker image inspect returned no image id")
	}
	return &inspection, nil
}

func (s *LocalStore) tagReference(packageInfo Package) string {
	return "agentarea-mcp-packages/" + RepositoryPath(packageInfo.Ecosystem, packageInfo.Name) + ":" + ImageTag(packageInfo.Version)
}

func imageEntrypoint(image v1.Image) ([]string, error) {
	config, err := image.ConfigFile()
	if err != nil {
		return nil, fmt.Errorf("read package image config: %w", err)
	}
	return parseEntrypointLabel(config.Config.Labels)
}

func parseEntrypointLabel(labels map[string]string) ([]string, error) {
	if labels == nil {
		return nil, fmt.Errorf("package image is missing io.agentarea.mcp.entrypoint label")
	}
	value := labels["io.agentarea.mcp.entrypoint"]
	if value == "" {
		return nil, fmt.Errorf("package image is missing io.agentarea.mcp.entrypoint label")
	}
	var entrypoint []string
	if err := json.Unmarshal([]byte(value), &entrypoint); err != nil || len(entrypoint) == 0 {
		return nil, fmt.Errorf("package image has invalid io.agentarea.mcp.entrypoint label")
	}
	return entrypoint, nil
}

func immutableReference(repositoryPath, digest string) string {
	return repositoryPath + "@" + digest
}

func registryNotFound(err error) bool {
	var transportErr *transport.Error
	return errors.As(err, &transportErr) && transportErr.StatusCode == 404
}
