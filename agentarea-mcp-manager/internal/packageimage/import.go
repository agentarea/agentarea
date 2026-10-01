package packageimage

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/mcpbase"
	"github.com/agentarea/mcp-manager/internal/mcpgateway"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/providers"
	"github.com/agentarea/mcp-manager/internal/secrets"
	"golang.org/x/sync/singleflight"
)

const (
	packageRoleLabel = "agentarea.io/role"
	packageRoleValue = "package-import"
	packSmokeTimeout = "120"
)

// InstanceRepository is the gateway repository seam needed by the import API.
type InstanceRepository interface {
	LoadInstance(context.Context, string) (*models.MCPServerInstance, error)
}

// Options configures an authenticated package importer.
type Options struct {
	Repository        InstanceRepository
	Backend           backends.Backend
	Remote            *mcpgateway.RemoteUpstream
	Secrets           secrets.SecretResolver
	Store             ImageStore
	PackageRepository string
	BackendType       string
	DockerRuntime     string
	ImportTimeout     time.Duration
	NPMRegistryURL    string
	PyPIURL           string
	AuthSecret        string
	HTTPClient        *http.Client
	Logger            *slog.Logger
}

// Service resolves command connections, builds package images, and serves the
// manager's authenticated package-import endpoint.
type Service struct {
	repository        InstanceRepository
	backend           backends.Backend
	remote            *mcpgateway.RemoteUpstream
	secrets           secrets.SecretResolver
	store             ImageStore
	packageRepository string
	backendType       string
	dockerRuntime     string
	resolver          *VersionResolver
	timeout           time.Duration
	authSecret        string
	httpClient        *http.Client
	logger            *slog.Logger
	flight            singleflight.Group
	storeOnce         sync.Once
	storeErr          error
}

func NewService(options Options) (*Service, error) {
	if options.Repository == nil || options.Backend == nil {
		return nil, fmt.Errorf("package importer repository and backend are required")
	}
	// The same credential as the demand gateway, held to the same bar: an
	// empty secret would accept a bare "Bearer " header.
	if len(options.AuthSecret) < 32 {
		return nil, fmt.Errorf("package importer requires MCP_GATEWAY_AUTH_SECRET of at least 32 characters")
	}
	if options.ImportTimeout <= 0 {
		options.ImportTimeout = 15 * time.Minute
	}
	if options.Logger == nil {
		options.Logger = slog.Default()
	}
	if options.HTTPClient == nil {
		options.HTTPClient = &http.Client{Timeout: 10 * time.Second}
	}
	return &Service{
		repository:        options.Repository,
		backend:           options.Backend,
		remote:            options.Remote,
		secrets:           options.Secrets,
		store:             options.Store,
		packageRepository: strings.TrimRight(options.PackageRepository, "/"),
		backendType:       strings.ToLower(strings.TrimSpace(options.BackendType)),
		dockerRuntime:     options.DockerRuntime,
		resolver: &VersionResolver{
			NPMRegistryURL: options.NPMRegistryURL,
			PyPIURL:        options.PyPIURL,
			Client:         options.HTTPClient,
		},
		timeout:    options.ImportTimeout,
		authSecret: options.AuthSecret,
		httpClient: options.HTTPClient,
		logger:     options.Logger,
	}, nil
}

// Import performs one package import and returns the immutable image and argv.
func (s *Service) Import(ctx context.Context, instanceID string) (ImportResponse, error) {
	if strings.TrimSpace(instanceID) == "" {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "instance_id is required", nil)
	}
	instance, err := s.repository.LoadInstance(ctx, instanceID)
	if errors.Is(err, mcpgateway.ErrInstanceNotFound) {
		return ImportResponse{}, newHTTPError(http.StatusNotFound, "MCP instance not found", nil)
	}
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "load MCP instance: "+err.Error(), nil)
	}
	if instance == nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "MCP repository returned an empty instance", nil)
	}
	if instanceType, _ := instance.JSONSpec["type"].(string); instanceType != "command" {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "package import requires a command instance", nil)
	}
	command, err := commandArgv(instance.JSONSpec)
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, err.Error(), nil)
	}
	invocation, err := ParseInvocation(command)
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, err.Error(), nil)
	}
	backendSpec, err := providers.BuildBackendInstanceSpec(instance, s.secrets)
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "resolve connection environment: "+err.Error(), nil)
	}
	if key := privateRegistryEnvironment(backendSpec.Environment); key != "" {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "private package registry environment is not supported: "+key, nil)
	}
	resolvedVersion, err := s.resolver.Resolve(ctx, invocation)
	if err != nil {
		status := http.StatusServiceUnavailable
		if errors.Is(err, ErrPackageNotFound) {
			status = http.StatusUnprocessableEntity
		}
		return ImportResponse{}, newHTTPError(status, "resolve package version: "+err.Error(), nil)
	}
	packageInfo := Package{Ecosystem: invocation.Ecosystem, Name: invocation.Package, Version: resolvedVersion}
	key := string(packageInfo.Ecosystem) + ":" + strings.ToLower(packageInfo.Name) + "@" + packageInfo.Version
	value, err, _ := s.flight.Do(key, func() (any, error) {
		return s.importResolved(ctx, instance, backendSpec, invocation, packageInfo)
	})
	if err != nil {
		return ImportResponse{}, err
	}
	result, ok := value.(ImportResponse)
	if !ok {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "package import returned an invalid result", nil)
	}
	return result, nil
}

// ImportResponse is the stable success payload of POST /packages/import.
type ImportResponse struct {
	Image   string   `json:"image"`
	Command []string `json:"command"`
	Port    int      `json:"port"`
	Package Package  `json:"package"`
	Built   bool     `json:"built"`
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

type PackLayerReport struct {
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

func (s *Service) importResolved(ctx context.Context, instance *models.MCPServerInstance, sourceSpec *providers.BackendInstanceSpec, invocation Invocation, packageInfo Package) (ImportResponse, error) {
	store, err := s.imageStore()
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, err.Error(), nil)
	}
	stored, err := store.Lookup(ctx, packageInfo)
	if err == nil {
		if stored == nil {
			return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "package image store returned no image", nil)
		}
		return ImportResponse{Image: stored.Ref, Command: stored.Entrypoint, Port: mcpbase.Port, Package: packageInfo, Built: false}, nil
	}
	if !errors.Is(err, ErrImageNotFound) {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, err.Error(), nil)
	}
	return s.buildAndStore(ctx, instance, sourceSpec, invocation, packageInfo, store)
}

func (s *Service) buildAndStore(ctx context.Context, instance *models.MCPServerInstance, sourceSpec *providers.BackendInstanceSpec, invocation Invocation, packageInfo Package, store ImageStore) (response ImportResponse, resultErr error) {
	packID := packInstanceID(packageInfo)
	packSpec := backendPackSpec(instance, sourceSpec, invocation, packageInfo, packID)
	defer func() {
		cleanupCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := s.backend.DeleteInstance(cleanupCtx, packID); err != nil && !errors.Is(err, backends.ErrInstanceNotFound) {
			s.logger.Error("package pack workload cleanup failed", slog.String("instance_id", packID), slog.String("error", err.Error()))
			if resultErr == nil {
				resultErr = newHTTPError(http.StatusServiceUnavailable, "delete package pack workload: "+err.Error(), nil)
			}
		}
	}()
	if _, err := s.backend.CreateInstance(ctx, packSpec); err != nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "create package pack workload: "+err.Error(), nil)
	}

	packCtx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()
	report, layerPath, err := s.fetchPackResult(packCtx, packID)
	if err != nil {
		return ImportResponse{}, err
	}
	if report == nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "package pack workload returned no report", nil)
	}
	if layerPath != "" {
		defer os.Remove(layerPath)
	}
	if !report.OK {
		message := report.Error
		if message == "" {
			message = "package pack workload failed"
		}
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, message, report)
	}
	if report.Ecosystem != string(packageInfo.Ecosystem) || report.Package != packageInfo.Name || report.Version != packageInfo.Version {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "package pack report does not match the requested package", report)
	}
	if report.Layer == nil || report.Layer.SHA256 == "" {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "package pack report has no layer", report)
	}
	if err := verifyLayer(layerPath, report.Layer); err != nil {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, err.Error(), report)
	}
	finalCommand := append(append([]string(nil), report.Entrypoint...), invocation.Args...)
	if len(finalCommand) == 0 {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, "package pack report has no entrypoint", report)
	}
	base, err := store.Base(packCtx)
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "load mcp-base image: "+err.Error(), report)
	}
	assembled, err := AssembleImage(base, layerPath, packageInfo, finalCommand)
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusUnprocessableEntity, err.Error(), report)
	}
	stored, err := store.Put(packCtx, packageInfo, finalCommand, assembled)
	if err != nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, err.Error(), report)
	}
	if stored == nil {
		return ImportResponse{}, newHTTPError(http.StatusServiceUnavailable, "package image store returned no image", report)
	}
	return ImportResponse{Image: stored.Ref, Command: finalCommand, Port: mcpbase.Port, Package: packageInfo, Built: true}, nil
}

func (s *Service) fetchPackResult(ctx context.Context, instanceID string) (*PackReport, string, error) {
	deadline := time.Now().Add(s.timeout)
	for {
		status, err := s.backend.GetInstanceStatus(ctx, instanceID)
		if err == nil {
			if status == nil {
				return nil, "", newHTTPError(http.StatusServiceUnavailable, "package pack backend returned no status", nil)
			}
			if stoppedPackageStatus(status.Status) {
				return nil, "", newHTTPError(http.StatusServiceUnavailable, fmt.Sprintf("package pack workload stopped (state %q)", status.Status), nil)
			}
			if status.Status == "running" || status.Status == "healthy" || status.Status == "ready" {
				baseURL := s.packBaseURL(instanceID, status)
				if baseURL != "" && s.health(ctx, baseURL) {
					report, layerPath, fetchErr := s.fetchReportAndLayer(ctx, baseURL)
					if fetchErr == nil || report != nil {
						return report, layerPath, nil
					}
				}
			}
		} else if !errors.Is(err, backends.ErrInstanceNotFound) {
			return nil, "", newHTTPError(http.StatusServiceUnavailable, "inspect package pack workload: "+err.Error(), nil)
		}
		if !time.Now().Before(deadline) {
			return nil, "", newHTTPError(http.StatusServiceUnavailable, "package pack workload did not become reachable before timeout", nil)
		}
		select {
		case <-ctx.Done():
			return nil, "", newHTTPError(http.StatusServiceUnavailable, "package pack workload timed out: "+ctx.Err().Error(), nil)
		case <-time.After(250 * time.Millisecond):
		}
	}
}

func (s *Service) fetchReportAndLayer(ctx context.Context, baseURL string) (*PackReport, string, error) {
	reportURL := strings.TrimRight(baseURL, "/") + "/report"
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, reportURL, nil)
	if err != nil {
		return nil, "", err
	}
	s.setRemoteAuth(request)
	response, err := s.httpClient.Do(request)
	if err != nil {
		return nil, "", err
	}
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	response.Body.Close()
	if readErr != nil {
		return nil, "", readErr
	}
	if response.StatusCode != http.StatusOK {
		return nil, "", fmt.Errorf("package pack report returned HTTP %d", response.StatusCode)
	}
	var report PackReport
	if err := json.Unmarshal(body, &report); err != nil {
		return nil, "", fmt.Errorf("decode package pack report: %w", err)
	}
	if !report.OK || report.Layer == nil {
		return &report, "", nil
	}
	layerURL := strings.TrimRight(baseURL, "/") + "/layer.tar"
	layerRequest, err := http.NewRequestWithContext(ctx, http.MethodGet, layerURL, nil)
	if err != nil {
		return &report, "", err
	}
	s.setRemoteAuth(layerRequest)
	layerResponse, err := s.httpClient.Do(layerRequest)
	if err != nil {
		return &report, "", err
	}
	defer layerResponse.Body.Close()
	if layerResponse.StatusCode != http.StatusOK {
		return &report, "", fmt.Errorf("package pack layer returned HTTP %d", layerResponse.StatusCode)
	}
	file, err := os.CreateTemp(os.TempDir(), "mcp-package-layer-*.tar")
	if err != nil {
		return &report, "", fmt.Errorf("create package layer file: %w", err)
	}
	path := file.Name()
	if _, err := io.Copy(file, layerResponse.Body); err != nil {
		file.Close()
		os.Remove(path)
		return &report, "", fmt.Errorf("download package layer: %w", err)
	}
	if err := file.Close(); err != nil {
		os.Remove(path)
		return &report, "", fmt.Errorf("close package layer file: %w", err)
	}
	return &report, path, nil
}

func (s *Service) health(ctx context.Context, baseURL string) bool {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/health", nil)
	if err != nil {
		return false
	}
	s.setRemoteAuth(request)
	response, err := s.httpClient.Do(request)
	if err != nil {
		return false
	}
	if _, err := io.Copy(io.Discard, response.Body); err != nil {
		response.Body.Close()
		return false
	}
	response.Body.Close()
	return response.StatusCode == http.StatusOK
}

func (s *Service) packBaseURL(instanceID string, status *backends.InstanceStatus) string {
	if s.remote != nil {
		return strings.TrimRight(s.remote.BaseURL, "/") + "/dataplane/v1/instances/" + instanceID + "/proxy"
	}
	return strings.TrimRight(status.InternalURL, "/")
}

func (s *Service) setRemoteAuth(request *http.Request) {
	if s.remote != nil {
		request.Header.Set("Authorization", "Bearer "+s.remote.Token)
	}
}

func (s *Service) imageStore() (ImageStore, error) {
	if s.store != nil {
		return s.store, nil
	}
	s.storeOnce.Do(func() {
		switch {
		case s.packageRepository != "":
			s.store = NewRegistryStore(s.packageRepository)
		case s.backendType == "docker" || s.backendType == "podman":
			s.store = NewLocalStore(s.dockerRuntime)
		default:
			s.storeErr = fmt.Errorf("package images need MCP_PACKAGE_REPOSITORY")
		}
	})
	if s.storeErr != nil {
		return nil, s.storeErr
	}
	return s.store, nil
}

func backendPackSpec(instance *models.MCPServerInstance, source *providers.BackendInstanceSpec, invocation Invocation, packageInfo Package, packID string) *backends.InstanceSpec {
	environment := make(map[string]string, len(source.Environment)+6)
	for key, value := range source.Environment {
		environment[key] = value
	}
	environment["MCP_BASE_PACK_ECOSYSTEM"] = string(packageInfo.Ecosystem)
	environment["MCP_BASE_PACK_PACKAGE"] = packageInfo.Name
	environment["MCP_BASE_PACK_VERSION"] = packageInfo.Version
	environment["MCP_BASE_PACK_EXECUTABLE"] = invocation.Executable
	environment["MCP_BASE_PACK_SMOKE_TIMEOUT"] = packSmokeTimeout
	environment["PORT"] = fmt.Sprintf("%d", mcpbase.Port)
	labels := make(map[string]string, len(source.Labels)+1)
	for key, value := range source.Labels {
		labels[key] = value
	}
	labels[packageRoleLabel] = packageRoleValue
	return &backends.InstanceSpec{
		InstanceID:    packID,
		WorkspaceID:   instance.WorkspaceID,
		Name:          packID,
		ServiceName:   packID,
		Image:         mcpbase.Image(),
		Port:          mcpbase.Port,
		Environment:   environment,
		Labels:        labels,
		Command:       append([]string(nil), invocation.Args...),
		IsolationTier: source.IsolationTier,
		Resources: backends.ResourceRequirements{
			Limits:   backends.ResourceList{CPU: source.Resources.Limits.CPU, Memory: source.Resources.Limits.Memory},
			Requests: backends.ResourceList{CPU: source.Resources.Requests.CPU, Memory: source.Resources.Requests.Memory},
		},
	}
}

func commandArgv(jsonSpec map[string]interface{}) ([]string, error) {
	command, ok := jsonSpec["command"].(string)
	if !ok || command == "" {
		return nil, fmt.Errorf("command field must be a non-empty string")
	}
	args := []string{command}
	switch values := jsonSpec["args"].(type) {
	case []interface{}:
		for _, value := range values {
			item, ok := value.(string)
			if !ok {
				return nil, fmt.Errorf("command args must be strings")
			}
			args = append(args, item)
		}
	case []string:
		args = append(args, values...)
	case nil:
	default:
		return nil, fmt.Errorf("command args must be an array")
	}
	return args, nil
}

func packInstanceID(packageInfo Package) string {
	digest := sha256.Sum256([]byte(string(packageInfo.Ecosystem) + ":" + packageInfo.Name + "@" + packageInfo.Version))
	return "pack-" + hex.EncodeToString(digest[:])[:12]
}

func verifyLayer(path string, report *PackLayerReport) error {
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open fetched package layer: %w", err)
	}
	defer file.Close()
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

func stoppedPackageStatus(status string) bool {
	switch strings.ToLower(status) {
	case "stopped", "exited", "dead", "error", "failed":
		return true
	default:
		return false
	}
}

// ServeHTTP implements POST /packages/import.
func (s *Service) ServeHTTP(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		writeJSON(response, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
		return
	}
	if !authorized(request.Header.Get("X-AgentArea-Manager-Authorization"), s.authSecret) {
		writeJSON(response, http.StatusUnauthorized, map[string]any{"error": "unauthorized"})
		return
	}
	var body struct {
		InstanceID string `json:"instance_id"`
	}
	decoder := json.NewDecoder(io.LimitReader(request.Body, 1<<20))
	if err := decoder.Decode(&body); err != nil {
		writeJSON(response, http.StatusUnprocessableEntity, map[string]any{"error": "invalid request body: " + err.Error(), "report": nil})
		return
	}
	result, err := s.Import(request.Context(), body.InstanceID)
	if err == nil {
		writeJSON(response, http.StatusOK, result)
		return
	}
	var httpErr *HTTPError
	if !errors.As(err, &httpErr) {
		httpErr = newHTTPError(http.StatusServiceUnavailable, err.Error(), nil)
	}
	logAttrs := []any{slog.String("instance_id", body.InstanceID), slog.Int("status", httpErr.Code), slog.String("error", httpErr.Message)}
	if httpErr.Report != nil && httpErr.Report.LogTail != "" {
		logAttrs = append(logAttrs, slog.String("log_tail", httpErr.Report.LogTail))
	}
	s.logger.Warn("MCP package import failed", logAttrs...)
	payload := map[string]any{"error": httpErr.Message}
	if httpErr.Code == http.StatusUnprocessableEntity {
		payload["report"] = httpErr.Report
	}
	writeJSON(response, httpErr.Code, payload)
}

type HTTPError struct {
	Code    int
	Message string
	Report  *PackReport
}

func (e *HTTPError) Error() string { return e.Message }

func newHTTPError(code int, message string, report *PackReport) *HTTPError {
	return &HTTPError{Code: code, Message: message, Report: report}
}

func authorized(value, secret string) bool {
	presented, ok := strings.CutPrefix(value, "Bearer ")
	if !ok || len(presented) != len(secret) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(presented), []byte(secret)) == 1
}

func writeJSON(response http.ResponseWriter, status int, payload any) {
	response.Header().Set("Content-Type", "application/json")
	response.WriteHeader(status)
	if err := json.NewEncoder(response).Encode(payload); err != nil {
		return
	}
}
