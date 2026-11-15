// Package packages converts an npx/uvx command connection into an immutable
// image: it resolves the exact release, runs the mcp-base pack workload that
// installs and smoke-tests it, verifies the layer the workload hands back,
// appends it to the base image and stores the result, once per release.
package packages

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sync/singleflight"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

const (
	packageRoleLabel = "agentarea.io/role"
	packageRoleValue = "package-import"
	packSmokeTimeout = "120"
	packPollInterval = 250 * time.Millisecond
	packCleanup      = 30 * time.Second
)

// Workloads is the spec a command instance would start with, secrets
// resolved, and the instance's merged JSON spec (the runtime).
type Workloads interface {
	Workload(ctx context.Context, instanceID string) (workload.Spec, map[string]any, error)
}

// Remote is the data plane the pack workload runs behind, when there is one.
type Remote interface {
	InstanceProxyURL(instanceID string) string
	Authorize(r *http.Request) bool
}

// Options wire an Importer.
type Options struct {
	Config    Config
	Workloads Workloads
	Backend   workload.Backend
	// Remote is set when workloads run on a data plane.
	Remote Remote
	// LocalImages is true when the backend runs images from the local
	// container runtime, the only place a store without a repository reaches.
	LocalImages bool
	// Registries reaches package indexes and image registries (vendor egress).
	Registries *http.Client
	// Pack reaches the pack workload (internal egress).
	Pack *http.Client
	// Store replaces the store Config selects.
	Store ImageStore
	Log   *slog.Logger
}

// Importer turns command connections into package images.
type Importer struct {
	workloads Workloads
	backend   workload.Backend
	remote    Remote
	pack      *http.Client
	store     ImageStore
	resolver  *VersionResolver
	timeout   time.Duration
	flight    singleflight.Group
	log       *slog.Logger
}

// New builds an Importer. Without AGENTAREA_MCP_PACKAGE_REPO the images stay
// in the local runtime's store, which only a local backend can run from.
func New(o Options) (*Importer, error) {
	switch {
	case o.Workloads == nil || o.Backend == nil:
		return nil, errors.New("packages: Workloads and Backend are required")
	case o.Registries == nil || o.Pack == nil:
		return nil, errors.New("packages: Registries and Pack HTTP clients are required")
	case o.Log == nil:
		return nil, errors.New("packages: Log is required")
	case o.Config.Timeout <= 0:
		return nil, errors.New("packages: import timeout must be positive")
	}
	store := o.Store
	switch {
	case store != nil:
	case o.Config.Repository != "":
		store = NewRegistryStore(o.Config.Repository, o.Registries.Transport)
	case o.LocalImages:
		store = NewLocalStore(o.Config.Runtime)
	default:
		return nil, errors.New("packages: package images need AGENTAREA_MCP_PACKAGE_REPO when workloads do not run on the local container runtime")
	}
	return &Importer{
		workloads: o.Workloads,
		backend:   o.Backend,
		remote:    o.Remote,
		pack:      o.Pack,
		store:     store,
		resolver:  &VersionResolver{NPMRegistryURL: o.Config.NPMRegistry, PyPIURL: o.Config.PyPI, Client: o.Registries},
		timeout:   o.Config.Timeout,
		log:       o.Log,
	}, nil
}

// PackReport is the mcp-base pack workload report.
type PackReport struct {
	OK            bool             `json:"ok"`
	Ecosystem     string           `json:"ecosystem"`
	Package       string           `json:"package"`
	Version       string           `json:"version"`
	Entrypoint    []string         `json:"entrypoint"`
	Tools         int              `json:"tools"`
	OutsideWrites []string         `json:"outside_writes"`
	Error         string           `json:"error"`
	LogTail       string           `json:"log_tail"`
	Layer         *PackLayerReport `json:"layer"`
}

// PackLayerReport identifies the layer the pack workload serves.
type PackLayerReport struct {
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

type spawn struct {
	spec       workload.Spec
	invocation Invocation
	pkg        Package
}

// Import converts the instance's package into an image. A
// *service.PackageRejectedError is final; any other error is worth retrying.
func (i *Importer) Import(ctx context.Context, instanceID string) (service.ImportedPackage, error) {
	if strings.TrimSpace(instanceID) == "" {
		return service.ImportedPackage{}, reject("instance_id is required")
	}
	spec, jsonSpec, err := i.workloads.Workload(ctx, instanceID)
	if err != nil {
		var refused interface{ FailureReason() string }
		if errors.As(err, &refused) {
			return service.ImportedPackage{}, reject(refused.FailureReason())
		}
		return service.ImportedPackage{}, fmt.Errorf("load MCP instance %s: %w", instanceID, err)
	}
	if kind, _ := jsonSpec["type"].(string); kind != "command" {
		return service.ImportedPackage{}, reject("package import requires a command instance")
	}
	command, err := commandArgv(jsonSpec)
	if err != nil {
		return service.ImportedPackage{}, reject(err.Error())
	}
	invocation, err := ParseInvocation(command)
	if err != nil {
		return service.ImportedPackage{}, reject(err.Error())
	}
	if key := privateRegistryEnvironment(spec.Environment); key != "" {
		return service.ImportedPackage{}, reject("private package registry environment is not supported: " + key)
	}
	version, err := i.resolver.Resolve(ctx, invocation)
	if errors.Is(err, ErrPackageNotFound) {
		return service.ImportedPackage{}, reject("resolve package version: " + err.Error())
	}
	if err != nil {
		return service.ImportedPackage{}, fmt.Errorf("resolve package version: %w", err)
	}
	pkg := Package{Ecosystem: invocation.Ecosystem, Name: invocation.Package, Version: version}
	key := string(pkg.Ecosystem) + ":" + strings.ToLower(pkg.Name) + "@" + pkg.Version
	value, err, _ := i.flight.Do(key, func() (any, error) {
		return i.importResolved(ctx, spawn{spec: spec, invocation: invocation, pkg: pkg})
	})
	if err != nil {
		return service.ImportedPackage{}, err
	}
	stored, ok := value.(StoredImage)
	if !ok {
		return service.ImportedPackage{}, fmt.Errorf("package import returned %T", value)
	}
	return service.ImportedPackage{
		Image:   stored.Ref,
		Command: stored.Entrypoint,
		Port:    spec.Port,
		Package: map[string]any{"ecosystem": string(pkg.Ecosystem), "name": pkg.Name, "version": pkg.Version},
	}, nil
}

func (i *Importer) importResolved(ctx context.Context, s spawn) (StoredImage, error) {
	stored, err := i.store.Lookup(ctx, s.pkg)
	if err == nil {
		return stored, nil
	}
	if !errors.Is(err, ErrImageNotFound) {
		return StoredImage{}, err
	}
	return i.buildAndStore(ctx, s)
}

func (i *Importer) buildAndStore(ctx context.Context, s spawn) (stored StoredImage, resultErr error) {
	packID := packInstanceID(s.pkg)
	defer func() {
		cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), packCleanup)
		defer cancel()
		if err := i.backend.Delete(cleanupCtx, packID); err != nil {
			resultErr = errors.Join(resultErr, fmt.Errorf("delete package pack workload %s: %w", packID, err))
		}
	}()
	if _, err := i.backend.Create(ctx, packSpec(s, packID)); err != nil {
		return StoredImage{}, fmt.Errorf("create package pack workload: %w", err)
	}

	packCtx, cancel := context.WithTimeout(ctx, i.timeout)
	defer cancel()
	report, layerPath, err := i.fetchPackResult(packCtx, packID)
	if err != nil {
		return StoredImage{}, err
	}
	if layerPath != "" {
		defer func() {
			if err := removeFile(layerPath); err != nil {
				i.log.ErrorContext(ctx, "package layer cleanup failed", slog.String("path", layerPath), slog.String("error", err.Error()))
			}
		}()
	}
	if err := checkReport(report, s.pkg); err != nil {
		i.log.WarnContext(ctx, "MCP package pack rejected", slog.String("package", s.pkg.Name), slog.String("version", s.pkg.Version),
			slog.String("error", err.Error()), slog.String("log_tail", report.LogTail))
		return StoredImage{}, err
	}
	if err := verifyLayer(layerPath, report.Layer); err != nil {
		return StoredImage{}, reject(err.Error())
	}
	entrypoint := append(append([]string(nil), report.Entrypoint...), s.invocation.Args...)
	base, err := i.store.Base(packCtx, s.spec.Image)
	if err != nil {
		return StoredImage{}, fmt.Errorf("load base image: %w", err)
	}
	assembled, err := AssembleImage(base, layerPath, s.pkg, entrypoint)
	if err != nil {
		return StoredImage{}, reject(err.Error())
	}
	return i.store.Put(packCtx, s.pkg, entrypoint, assembled)
}

func checkReport(report PackReport, pkg Package) error {
	switch {
	case !report.OK:
		if report.Error == "" {
			return reject("package pack workload failed")
		}
		return reject(report.Error)
	case report.Ecosystem != string(pkg.Ecosystem) || report.Package != pkg.Name || report.Version != pkg.Version:
		return reject("package pack report does not match the requested package")
	case report.Layer == nil || report.Layer.SHA256 == "":
		return reject("package pack report has no layer")
	case len(report.Entrypoint) == 0:
		return reject("package pack report has no entrypoint")
	}
	return nil
}

// fetchPackResult waits for the pack workload to answer /health, then reads
// its report and, for a successful pack, downloads its layer.
func (i *Importer) fetchPackResult(ctx context.Context, packID string) (PackReport, string, error) {
	var lastProbe error
	for {
		status, err := i.backend.Status(ctx, packID)
		switch {
		case errors.Is(err, workload.ErrNotFound):
		case err != nil:
			return PackReport{}, "", fmt.Errorf("inspect package pack workload: %w", err)
		case status.Status == workload.StatusStopped:
			return PackReport{}, "", fmt.Errorf("package pack workload stopped: %s", status.Message)
		case status.Status == workload.StatusRunning:
			baseURL, err := i.packBaseURL(packID, status)
			if err != nil {
				return PackReport{}, "", err
			}
			if lastProbe = i.health(ctx, baseURL); lastProbe == nil {
				return i.fetchReportAndLayer(ctx, baseURL)
			}
		}
		select {
		case <-ctx.Done():
			return PackReport{}, "", errors.Join(fmt.Errorf("package pack workload did not answer: %w", ctx.Err()), lastProbe)
		case <-time.After(packPollInterval):
		}
	}
}

func (i *Importer) fetchReportAndLayer(ctx context.Context, baseURL string) (PackReport, string, error) {
	response, err := i.get(ctx, baseURL+"/report")
	if err != nil {
		return PackReport{}, "", fmt.Errorf("fetch package pack report: %w", err)
	}
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	if err := errors.Join(readErr, response.Body.Close()); err != nil {
		return PackReport{}, "", fmt.Errorf("read package pack report: %w", err)
	}
	if response.StatusCode != http.StatusOK {
		return PackReport{}, "", fmt.Errorf("package pack report returned HTTP %d", response.StatusCode)
	}
	var report PackReport
	if err := json.Unmarshal(body, &report); err != nil {
		return PackReport{}, "", fmt.Errorf("decode package pack report: %w", err)
	}
	if !report.OK || report.Layer == nil {
		return report, "", nil
	}
	path, err := i.downloadLayer(ctx, baseURL+"/layer.tar")
	return report, path, err
}

func (i *Importer) downloadLayer(ctx context.Context, layerURL string) (path string, err error) {
	response, err := i.get(ctx, layerURL)
	if err != nil {
		return "", fmt.Errorf("fetch package layer: %w", err)
	}
	defer func() { err = errors.Join(err, response.Body.Close()) }()
	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("package pack layer returned HTTP %d", response.StatusCode)
	}
	file, err := os.CreateTemp("", "mcp-package-layer-*.tar")
	if err != nil {
		return "", fmt.Errorf("create package layer file: %w", err)
	}
	path = file.Name()
	if _, err := io.Copy(file, response.Body); err != nil {
		return "", errors.Join(fmt.Errorf("download package layer: %w", err), file.Close(), removeFile(path))
	}
	if err := file.Close(); err != nil {
		return "", errors.Join(fmt.Errorf("close package layer file: %w", err), removeFile(path))
	}
	return path, nil
}

func (i *Importer) health(ctx context.Context, baseURL string) error {
	response, err := i.get(ctx, baseURL+"/health")
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(io.Discard, response.Body)
	if err := errors.Join(copyErr, response.Body.Close()); err != nil {
		return err
	}
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("package pack health returned HTTP %d", response.StatusCode)
	}
	return nil
}

func (i *Importer) get(ctx context.Context, target string) (*http.Response, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, err
	}
	if i.remote != nil && !i.remote.Authorize(request) {
		return nil, fmt.Errorf("pack workload URL %s is outside the data plane", target)
	}
	return i.pack.Do(request)
}

func (i *Importer) packBaseURL(packID string, status workload.Status) (string, error) {
	if i.remote != nil {
		return strings.TrimSuffix(i.remote.InstanceProxyURL(packID), "/mcp"), nil
	}
	if status.InternalURL == "" {
		return "", errors.New("package pack workload runs without an internal URL")
	}
	return strings.TrimRight(status.InternalURL, "/"), nil
}

func packSpec(s spawn, packID string) workload.Spec {
	environment := make(map[string]string, len(s.spec.Environment)+6)
	for key, value := range s.spec.Environment {
		environment[key] = value
	}
	environment["MCP_BASE_PACK_ECOSYSTEM"] = string(s.pkg.Ecosystem)
	environment["MCP_BASE_PACK_PACKAGE"] = s.pkg.Name
	environment["MCP_BASE_PACK_VERSION"] = s.pkg.Version
	environment["MCP_BASE_PACK_EXECUTABLE"] = s.invocation.Executable
	environment["MCP_BASE_PACK_SMOKE_TIMEOUT"] = packSmokeTimeout
	environment["PORT"] = strconv.Itoa(s.spec.Port)
	labels := make(map[string]string, len(s.spec.Labels)+1)
	for key, value := range s.spec.Labels {
		labels[key] = value
	}
	labels[packageRoleLabel] = packageRoleValue
	return workload.Spec{
		InstanceID:    packID,
		WorkspaceID:   s.spec.WorkspaceID,
		Name:          packID,
		ServiceName:   packID,
		Image:         s.spec.Image,
		Port:          s.spec.Port,
		Environment:   environment,
		Labels:        labels,
		Command:       append([]string(nil), s.invocation.Args...),
		IsolationTier: s.spec.IsolationTier,
		Resources:     s.spec.Resources,
	}
}

func commandArgv(jsonSpec map[string]any) ([]string, error) {
	command, ok := jsonSpec["command"].(string)
	if !ok || command == "" {
		return nil, errors.New("command field must be a non-empty string")
	}
	args := []string{command}
	switch values := jsonSpec["args"].(type) {
	case []any:
		for _, value := range values {
			item, ok := value.(string)
			if !ok {
				return nil, errors.New("command args must be strings")
			}
			args = append(args, item)
		}
	case []string:
		args = append(args, values...)
	case nil:
	default:
		return nil, errors.New("command args must be an array")
	}
	return args, nil
}

func packInstanceID(pkg Package) string {
	digest := sha256.Sum256([]byte(string(pkg.Ecosystem) + ":" + pkg.Name + "@" + pkg.Version))
	return "pack-" + hex.EncodeToString(digest[:])[:12]
}

func verifyLayer(path string, report *PackLayerReport) (err error) {
	file, err := os.Open(path) //nolint:gosec // path is the temp file the layer was downloaded to
	if err != nil {
		return fmt.Errorf("open fetched package layer: %w", err)
	}
	defer func() { err = errors.Join(err, file.Close()) }()
	hash := sha256.New()
	size, err := io.Copy(hash, file)
	if err != nil {
		return fmt.Errorf("hash fetched package layer: %w", err)
	}
	actual := hex.EncodeToString(hash.Sum(nil))
	if !strings.EqualFold(actual, report.SHA256) {
		return fmt.Errorf("package layer sha256 mismatch: report %s, fetched %s", report.SHA256, actual)
	}
	if report.Size > 0 && size != report.Size {
		return fmt.Errorf("package layer size mismatch: report %d, fetched %d", report.Size, size)
	}
	return nil
}

func reject(msg string) error { return &service.PackageRejectedError{Msg: msg} }
