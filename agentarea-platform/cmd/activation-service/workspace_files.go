package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/activationauth"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/workspace"
)

// maxFileContentBytes bounds the inline JSON/base64 endpoint.
// The raw /files/content endpoint is governed by the control-plane workspace
// quota and streams directly to disk.
const maxFileContentBytes = 16 * 1024 * 1024

// FilesPutRequest writes a single file into the per-task workspace on the same
// filesystem bash executes against, so the agent's file tool and its shell see
// one workspace.
type FilesPutRequest struct {
	WorkspaceID         string `json:"workspace_id"`
	TaskID              string `json:"task_id"`
	ExecutorIncarnation string `json:"executor_incarnation,omitempty"`
	Path                string `json:"path"`
	ContentBase64       string `json:"content_base64"`
}

// FilesPutResponse acknowledges a written file.
type FilesPutResponse struct {
	Path string `json:"path"`
	Size int64  `json:"size"`
}

// FilesGetResponse returns a single file's contents.
type FilesGetResponse struct {
	ContentBase64 string `json:"content_base64"`
	Size          int64  `json:"size"`
}

// FilesListResponse lists the regular files under a prefix.
type FilesListResponse struct {
	Paths []string `json:"paths"`
}

// filesHandler serves the sandbox file API. Writes and reads target the same
// per-task workspace directory the /execute command runs in, giving the agent's
// file tool and its bash a shared filesystem.
func (s *server) filesHandler(w http.ResponseWriter, r *http.Request) {
	s.beginRequest()
	defer s.endRequest()
	switch r.Method {
	case http.MethodPut:
		s.filesPutHandler(w, r)
	case http.MethodGet:
		s.filesGetHandler(w, r)
	default:
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

// fileContentHandler is the constant-memory transfer path used for task input
// hydration, artifact publication, and larger file-tool operations. The inline
// /files JSON/base64 endpoint remains bounded for compatibility with old
// clients; durable/live file movement must use this raw stream instead.
func (s *server) fileContentHandler(w http.ResponseWriter, r *http.Request) {
	s.beginRequest()
	defer s.endRequest()
	switch r.Method {
	case http.MethodPut:
		s.fileContentPutHandler(w, r)
	case http.MethodGet:
		s.fileContentGetHandler(w, r)
	default:
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

// fileUpload is the validated form of a streamed workspace write. Parsing it
// away from the handler keeps every rejection in one place, so no field reaches
// the filesystem on a path that skipped a check.
type fileUpload struct {
	workspaceID         string
	taskID              string
	executorIncarnation string
	clean               string
	expectedSHA256      string
	expectedSize        int64
	mode                uint32
}

func (s *server) parseFileUpload(r *http.Request) (fileUpload, int, error) {
	query := r.URL.Query()
	upload := fileUpload{
		workspaceID:         query.Get("workspace_id"),
		taskID:              query.Get("task_id"),
		executorIncarnation: query.Get("executor_incarnation"),
		expectedSHA256:      query.Get("sha256"),
	}
	pathParam := query.Get("path")
	expectedSize, sizeErr := strconv.ParseInt(query.Get("size"), 10, 64)
	modeValue, modeErr := strconv.ParseUint(query.Get("mode"), 8, 32)
	if err := workspace.ValidateIdentifier("workspace_id", upload.workspaceID); err != nil {
		return upload, http.StatusBadRequest, fmt.Errorf("invalid workspace_id")
	}
	if err := workspace.ValidateIdentifier("task_id", upload.taskID); err != nil {
		return upload, http.StatusBadRequest, fmt.Errorf("invalid task_id")
	}
	clean, pathErr := cleanSandboxRelativePath(pathParam)
	digest, digestErr := hex.DecodeString(upload.expectedSHA256)
	if pathErr != nil || strings.ContainsRune(pathParam, 0) || sizeErr != nil || expectedSize < 0 || modeErr != nil || modeValue == 0 || modeValue&^uint64(0o777) != 0 || digestErr != nil || len(digest) != sha256.Size || upload.expectedSHA256 != strings.ToLower(upload.expectedSHA256) {
		return upload, http.StatusBadRequest, fmt.Errorf("path, size, mode, and lowercase sha256 are required")
	}
	if expectedSize > s.policy.WorkspaceLimits.MaxFileBytes {
		return upload, http.StatusRequestEntityTooLarge, fmt.Errorf("file exceeds workspace per-file limit")
	}
	if r.ContentLength != expectedSize {
		return upload, http.StatusBadRequest, fmt.Errorf("Content-Length does not match declared size")
	}
	upload.clean = clean
	upload.expectedSize = expectedSize
	upload.mode = uint32(modeValue)
	return upload, http.StatusOK, nil
}

func (s *server) fileContentPutHandler(w http.ResponseWriter, r *http.Request) {
	upload, status, err := s.parseFileUpload(r)
	if err != nil {
		jsonError(w, err.Error(), status)
		return
	}
	workspaceID := upload.workspaceID
	taskID := upload.taskID
	executorIncarnation := upload.executorIncarnation
	clean := upload.clean
	expectedSHA256 := upload.expectedSHA256
	expectedSize := upload.expectedSize
	modeValue := upload.mode
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BoundTransferSHA256(http.MethodPut, clean, expectedSize, modeValue, expectedSHA256, executorIncarnation)) {
		return
	}
	if !s.requireExecutorIncarnation(w, executorIncarnation) {
		return
	}
	unlockWorkspace := s.lockWorkspaceMutation(workspaceID, taskID)
	defer unlockWorkspace()

	credential, err := s.sandboxCommandCredential()
	if err != nil {
		jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}
	workspaceDir, err := s.resolveExecutionWorkspace(workspaceID, taskID)
	if err != nil {
		jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer func() { _ = root.Close() }()
	if err := s.ensureWorkspaceFileSlot(root, workspaceDir, clean); err != nil {
		http.Error(w, `{"error": "workspace file limit exceeded"}`, http.StatusInsufficientStorage)
		return
	}
	dir := filepath.Dir(clean)
	if dir != "." {
		if err := mkdirAllOwned(root, dir, ownBySandbox(credential)); err != nil {
			http.Error(w, `{"error": "failed to create parent directory"}`, http.StatusInternalServerError)
			return
		}
	}
	tempName, err := streamedUploadTempName(dir, filepath.Base(clean))
	if err != nil {
		http.Error(w, `{"error": "failed to create upload identity"}`, http.StatusInternalServerError)
		return
	}
	temp, err := root.OpenFile(tempName, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		http.Error(w, `{"error": "failed to create temporary upload"}`, http.StatusInternalServerError)
		return
	}
	removeTemp := true
	defer func() {
		_ = temp.Close()
		if removeTemp {
			_ = root.Remove(tempName)
		}
	}()
	hasher := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(temp, hasher), io.LimitReader(r.Body, expectedSize+1))
	if copyErr != nil || written != expectedSize || hex.EncodeToString(hasher.Sum(nil)) != expectedSHA256 {
		http.Error(w, `{"error": "streamed file size or checksum mismatch"}`, http.StatusBadRequest)
		return
	}
	if err := temp.Sync(); err != nil {
		http.Error(w, `{"error": "failed to sync streamed file"}`, http.StatusInternalServerError)
		return
	}
	if err := prepareOwnedFile(temp, credential, fs.FileMode(modeValue)); err != nil {
		http.Error(w, `{"error": "failed to prepare streamed file ownership"}`, http.StatusInternalServerError)
		return
	}
	if err := temp.Close(); err != nil {
		http.Error(w, `{"error": "failed to close streamed file"}`, http.StatusInternalServerError)
		return
	}
	if err := root.Rename(tempName, clean); err != nil {
		http.Error(w, `{"error": "failed to commit streamed file"}`, http.StatusInternalServerError)
		return
	}
	removeTemp = false
	if err := enforceWorkspaceLimits(workspaceDir, s.policy.WorkspaceLimits); err != nil {
		s.rejectUnsafeWorkspace(w, workspaceDir, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesPutResponse{Path: clean, Size: written})
}

func (s *server) fileContentGetHandler(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	workspaceID := query.Get("workspace_id")
	taskID := query.Get("task_id")
	executorIncarnation := query.Get("executor_incarnation")
	pathParam := query.Get("path")
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		http.Error(w, `{"error": "invalid workspace_id"}`, http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		http.Error(w, `{"error": "invalid task_id"}`, http.StatusBadRequest)
		return
	}
	clean, err := cleanSandboxRelativePath(pathParam)
	if err != nil || strings.ContainsRune(pathParam, 0) {
		http.Error(w, `{"error": "path must be relative and canonical"}`, http.StatusBadRequest)
		return
	}
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BoundTransferSHA256(http.MethodGet, clean, -1, 0, activationauth.BodySHA256(nil), executorIncarnation)) {
		return
	}
	if !s.requireExecutorIncarnation(w, executorIncarnation) {
		return
	}
	workspaceDir, err := s.existingExecutionWorkspace(workspaceID, taskID)
	if errors.Is(err, os.ErrNotExist) {
		http.Error(w, `{"error": "task workspace expired"}`, http.StatusGone)
		return
	}
	if err != nil {
		jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer func() { _ = root.Close() }()
	info, err := root.Stat(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	if info.IsDir() {
		http.Error(w, `{"error": "path is a directory"}`, http.StatusBadRequest)
		return
	}
	file, err := root.Open(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	defer func() { _ = file.Close() }()
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.FormatInt(info.Size(), 10))
	w.Header().Set("X-AgentArea-File-Mode", fmt.Sprintf("%03o", info.Mode().Perm()))
	if _, err := io.Copy(w, file); err != nil {
		s.logger.Error("stream sandbox file", "workspace_id", workspaceID, "task_id", taskID, "path", clean, "error", err)
	}
}

func streamedUploadTempName(dir, base string) (string, error) {
	random := make([]byte, 16)
	if _, err := rand.Read(random); err != nil {
		return "", err
	}
	name := "." + base + ".agentarea-upload-" + hex.EncodeToString(random)
	if dir == "." {
		return name, nil
	}
	return filepath.Join(dir, name), nil
}

// workspaceTaskHandler removes one exact live task directory. Durable inputs
// and explicitly published artifacts remain in object storage; this endpoint
// owns only the executor's ephemeral working copy.
func (s *server) workspaceTaskHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodDelete {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	s.beginRequest()
	defer s.endRequest()

	workspaceID := r.URL.Query().Get("workspace_id")
	taskID := r.URL.Query().Get("task_id")
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		http.Error(w, `{"error": "invalid workspace_id"}`, http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		http.Error(w, `{"error": "invalid task_id"}`, http.StatusBadRequest)
		return
	}
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeCleanup, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(nil)) {
		return
	}
	unlockWorkspace := s.lockWorkspaceMutation(workspaceID, taskID)
	defer unlockWorkspace()

	dir, err := s.executionWorkspacePath(workspaceID, taskID)
	if err != nil {
		http.Error(w, `{"error": "invalid task workspace"}`, http.StatusBadRequest)
		return
	}
	if err := os.RemoveAll(dir); err != nil {
		http.Error(w, `{"error": "failed to delete task workspace"}`, http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *server) filesPutHandler(w http.ResponseWriter, r *http.Request) {
	body, err := readActivationRequestBody(r)
	if err != nil {
		jsonError(w, fmt.Sprintf("invalid request: %v", err), http.StatusBadRequest)
		return
	}
	var req FilesPutRequest
	if err := json.Unmarshal(body, &req); err != nil {
		jsonError(w, fmt.Sprintf("invalid request: %v", err), http.StatusBadRequest)
		return
	}
	if req.WorkspaceID == "" || req.TaskID == "" {
		http.Error(w, `{"error": "workspace_id and task_id are required"}`, http.StatusBadRequest)
		return
	}
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body)) {
		return
	}
	if !s.requireExecutorIncarnation(w, req.ExecutorIncarnation) {
		return
	}
	unlockWorkspace := s.lockWorkspaceMutation(req.WorkspaceID, req.TaskID)
	defer unlockWorkspace()
	clean, err := cleanSandboxRelativePath(req.Path)
	if err != nil || strings.ContainsRune(req.Path, 0) {
		http.Error(w, `{"error": "path must be relative and must not contain '..' or NUL"}`, http.StatusBadRequest)
		return
	}
	content, err := base64.StdEncoding.DecodeString(req.ContentBase64)
	if err != nil {
		http.Error(w, `{"error": "content_base64 is not valid base64"}`, http.StatusBadRequest)
		return
	}
	if len(content) > maxFileContentBytes {
		http.Error(w, `{"error": "file content is too large"}`, http.StatusRequestEntityTooLarge)
		return
	}
	if int64(len(content)) > s.policy.WorkspaceLimits.MaxFileBytes {
		http.Error(w, `{"error": "file exceeds workspace per-file limit"}`, http.StatusRequestEntityTooLarge)
		return
	}
	// Resolve the non-root identity before writing. When the service runs as
	// root the file MUST end up owned by the sandbox uid, otherwise the bash
	// command (which runs as that uid) could not read or overwrite it.
	credential, err := s.sandboxCommandCredential()
	if err != nil {
		jsonError(w, err.Error(), http.StatusInternalServerError)
		return
	}
	workspaceDir, err := s.resolveExecutionWorkspace(req.WorkspaceID, req.TaskID)
	if err != nil {
		jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	if err := prepareTaskWorkspace(workspaceDir, credential); err != nil {
		http.Error(w, `{"error": "failed to prepare non-root task workspace"}`, http.StatusInternalServerError)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer func() { _ = root.Close() }()
	if err := s.ensureWorkspaceFileSlot(root, workspaceDir, clean); err != nil {
		http.Error(w, `{"error": "workspace file limit exceeded"}`, http.StatusInsufficientStorage)
		return
	}
	if dir := filepath.Dir(clean); dir != "." {
		if err := mkdirAllOwned(root, dir, ownBySandbox(credential)); err != nil {
			http.Error(w, `{"error": "failed to create parent directory"}`, http.StatusInternalServerError)
			return
		}
	}
	if err := root.WriteFile(clean, content, 0o600); err != nil {
		http.Error(w, `{"error": "failed to write file"}`, http.StatusInternalServerError)
		return
	}
	written, err := root.OpenFile(clean, os.O_RDONLY, 0)
	if err != nil {
		http.Error(w, `{"error": "failed to reopen written file"}`, http.StatusInternalServerError)
		return
	}
	if err := prepareOwnedFile(written, credential, 0o600); err != nil {
		_ = written.Close()
		http.Error(w, `{"error": "failed to prepare written file ownership"}`, http.StatusInternalServerError)
		return
	}
	_ = written.Close()
	if err := enforceWorkspaceLimits(workspaceDir, s.policy.WorkspaceLimits); err != nil {
		s.rejectUnsafeWorkspace(w, workspaceDir, err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesPutResponse{Path: clean, Size: int64(len(content))})
}

func (s *server) filesGetHandler(w http.ResponseWriter, r *http.Request) {
	body, err := readActivationRequestBody(r)
	if err != nil {
		jsonError(w, fmt.Sprintf("invalid request: %v", err), http.StatusBadRequest)
		return
	}
	query := r.URL.Query()
	workspaceID := query.Get("workspace_id")
	taskID := query.Get("task_id")
	executorIncarnation := query.Get("executor_incarnation")
	if workspaceID == "" || taskID == "" {
		http.Error(w, `{"error": "workspace_id and task_id are required"}`, http.StatusBadRequest)
		return
	}
	operationPath := ""
	if query.Has("list") {
		prefix := query.Get("list")
		if prefix != "" {
			cleanPrefix, cleanErr := cleanSandboxRelativePath(prefix)
			if cleanErr != nil || cleanPrefix != prefix {
				http.Error(w, `{"error": "list prefix must be relative and canonical"}`, http.StatusBadRequest)
				return
			}
		}
		operationPath = "list:" + prefix
	} else {
		pathParam := query.Get("path")
		clean, cleanErr := cleanSandboxRelativePath(pathParam)
		if cleanErr != nil || strings.ContainsRune(pathParam, 0) {
			http.Error(w, `{"error": "path must be relative and must not contain '..' or NUL"}`, http.StatusBadRequest)
			return
		}
		operationPath = "file:" + clean
	}
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeFiles, activationauth.Identity{
		WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
	}, activationauth.BoundTransferSHA256(http.MethodGet, operationPath, -1, 0, activationauth.BodySHA256(body), executorIncarnation)) {
		return
	}
	if !s.requireExecutorIncarnation(w, executorIncarnation) {
		return
	}
	workspaceDir, err := s.existingExecutionWorkspace(workspaceID, taskID)
	if errors.Is(err, os.ErrNotExist) {
		http.Error(w, `{"error": "task workspace expired"}`, http.StatusGone)
		return
	}
	if err != nil {
		jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusInternalServerError)
		return
	}
	defer func() { _ = root.Close() }()

	if query.Has("list") {
		paths, err := s.listWorkspaceFiles(root, query.Get("list"))
		if err != nil {
			jsonError(w, err.Error(), http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(FilesListResponse{Paths: paths})
		return
	}

	pathParam := query.Get("path")
	clean, _ := cleanSandboxRelativePath(pathParam)
	info, err := root.Stat(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	if info.IsDir() {
		http.Error(w, `{"error": "path is a directory"}`, http.StatusBadRequest)
		return
	}
	if info.Size() > maxFileContentBytes {
		http.Error(w, `{"error": "file content is too large"}`, http.StatusRequestEntityTooLarge)
		return
	}
	data, err := root.ReadFile(clean)
	if err != nil {
		http.Error(w, `{"error": "file not found"}`, http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(FilesGetResponse{
		ContentBase64: base64.StdEncoding.EncodeToString(data),
		Size:          int64(len(data)),
	})
}

// listWorkspaceFiles returns the relative paths of regular files under prefix.
// It walks through os.Root so symlinks can never escape the task workspace.
func (s *server) listWorkspaceFiles(root *os.Root, prefix string) ([]string, error) {
	clean := ""
	if prefix != "" {
		var err error
		clean, err = cleanSandboxRelativePath(prefix)
		if err != nil || strings.ContainsRune(prefix, 0) {
			return nil, fmt.Errorf("prefix must be relative and must not contain '..' or NUL")
		}
		clean = filepath.ToSlash(clean)
	}
	paths := make([]string, 0)
	err := fs.WalkDir(root.FS(), ".", func(name string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() || entry.Type()&fs.ModeSymlink != 0 {
			return nil
		}
		if clean != "" && name != clean && !strings.HasPrefix(name, clean+"/") {
			return nil
		}
		paths = append(paths, name)
		if len(paths) > s.policy.WorkspaceLimits.MaxFiles {
			return fmt.Errorf("workspace file limit exceeded")
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	return paths, nil
}

func (s *server) workspaceWritebackHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error": "method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	s.beginRequest()
	defer s.endRequest()
	body, err := readActivationRequestBody(r)
	if err != nil {
		jsonError(w, fmt.Sprintf("invalid writeback request: %v", err), http.StatusBadRequest)
		return
	}
	var req workspace.WritebackRequest
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&req); err != nil {
		jsonError(w, fmt.Sprintf("invalid writeback request: %v", err), http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("workspace_id", req.WorkspaceID); err != nil {
		jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	if err := workspace.ValidateIdentifier("task_id", req.TaskID); err != nil || req.BaseGeneration < 0 || req.FencingToken <= 0 {
		http.Error(w, `{"error": "invalid task/generation/fencing identity"}`, http.StatusBadRequest)
		return
	}
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeWriteback, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
		Generation: req.BaseGeneration, FencingToken: req.FencingToken,
	}, activationauth.BodySHA256(body)) {
		return
	}
	workspaceDir, err := s.resolveExecutionWorkspace(req.WorkspaceID, req.TaskID)
	if err != nil {
		jsonError(w, err.Error(), http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(workspaceDir)
	if err != nil {
		http.Error(w, `{"error": "task workspace is unavailable"}`, http.StatusConflict)
		return
	}
	defer func() { _ = root.Close() }()
	allowedHost, endpointErr := s.objectStoreEndpointHost()
	if endpointErr != nil {
		http.Error(w, `{"error": "object store endpoint is not configured"}`, http.StatusInternalServerError)
		return
	}
	client := &http.Client{
		Timeout: 10 * time.Minute,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return fmt.Errorf("workspace transfer redirects are forbidden")
		},
	}
	response := workspace.WritebackResponse{Receipts: make([]workspace.UploadReceipt, 0, len(req.Uploads))}
	for _, upload := range req.Uploads {
		clean, pathErr := workspace.NormalizeRelativePath(upload.RelativePath)
		if pathErr != nil {
			http.Error(w, `{"error": "invalid output path"}`, http.StatusBadRequest)
			return
		}
		if upload.Deleted {
			response.Receipts = append(response.Receipts, workspace.UploadReceipt{RelativePath: clean, Deleted: true})
			continue
		}
		parsed, parseErr := url.Parse(upload.URL)
		if parseErr != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
			http.Error(w, `{"error": "invalid signed output URL"}`, http.StatusBadRequest)
			return
		}
		if parsed.Host != allowedHost {
			http.Error(w, `{"error": "signed output URL host is not the configured object store"}`, http.StatusForbidden)
			return
		}
		file, openErr := root.Open(clean)
		if openErr != nil {
			jsonError(w, fmt.Sprintf("output %s is missing", clean), http.StatusConflict)
			return
		}
		info, statErr := file.Stat()
		if statErr != nil || !info.Mode().IsRegular() || info.Size() != upload.Size {
			_ = file.Close()
			jsonError(w, fmt.Sprintf("output %s size/type changed", clean), http.StatusConflict)
			return
		}
		hasher := sha256.New()
		if _, hashErr := io.Copy(hasher, file); hashErr != nil || hex.EncodeToString(hasher.Sum(nil)) != upload.SHA256 {
			_ = file.Close()
			jsonError(w, fmt.Sprintf("output %s checksum changed", clean), http.StatusConflict)
			return
		}
		_, _ = file.Seek(0, io.SeekStart)
		putRequest, requestErr := http.NewRequestWithContext(r.Context(), http.MethodPut, parsed.String(), file)
		if requestErr != nil {
			_ = file.Close()
			http.Error(w, `{"error": "failed to create output upload"}`, http.StatusInternalServerError)
			return
		}
		putRequest.ContentLength = upload.Size
		applyTransferHeaders(putRequest, upload.Headers)
		putResponse, uploadErr := client.Do(putRequest)
		_ = file.Close()
		if uploadErr != nil {
			jsonError(w, fmt.Sprintf("output %s upload failed", clean), http.StatusBadGateway)
			return
		}
		_ = putResponse.Body.Close()
		if putResponse.StatusCode < 200 || putResponse.StatusCode >= 300 {
			jsonError(w, fmt.Sprintf("output %s upload returned status %d", clean, putResponse.StatusCode), http.StatusBadGateway)
			return
		}
		response.Receipts = append(response.Receipts, workspace.UploadReceipt{RelativePath: clean, ObjectURI: upload.ObjectURI})
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(response)
}
