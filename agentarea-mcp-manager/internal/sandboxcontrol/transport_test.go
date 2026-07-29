package sandboxcontrol

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestExecutionContractsRejectLegacyInlineFiles(t *testing.T) {
	canary := "REDIS-FILE-BODY-CANARY"
	encodedCanary := base64.StdEncoding.EncodeToString([]byte(canary))
	payloads := []string{
		fmt.Sprintf(`{"command":{"script_name":"cmd.sh","script_content":"true"},"input_files":[{"path":"secret.bin","content_base64":"%s"}]}`, encodedCanary),
		fmt.Sprintf(`{"command":{"script_name":"cmd.sh","script_content":"true","input_files":[{"path":"secret.bin","content_base64":"%s"}]}}`, encodedCanary),
		fmt.Sprintf(`{"command":{"script_name":"cmd.sh","script_content":"true"},"content_base64":"%s"}`, encodedCanary),
		fmt.Sprintf(`{"command":{"script_name":"cmd.sh","script_content":"true","content_base64":"%s"}}`, encodedCanary),
	}
	for _, payload := range payloads {
		var request ExecutionCreateRequest
		err := json.Unmarshal([]byte(payload), &request)
		if err == nil || !strings.Contains(err.Error(), "unsupported_contract_version") {
			t.Fatalf("legacy payload accepted: %s; error = %v", payload, err)
		}
	}

	encoded, err := json.Marshal(ExecutionCreateRequest{Command: warmpool.ExecuteRequest{CommandBody: "echo ok"}})
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"content_base64", "input_files", "script_content", "script_name"} {
		if strings.Contains(string(encoded), forbidden) {
			t.Fatalf("encoded execution request contains forbidden field %q: %s", forbidden, encoded)
		}
	}
}

func TestExecutionContractsRejectCallerControlledBodyChannels(t *testing.T) {
	canary := "REDIS-ARBITRARY-BODY-CANARY"
	payloads := []string{
		fmt.Sprintf(`{"metadata":{"note":%q},"command":{"command_path":".agentarea/commands/command.sh"}}`, canary),
		fmt.Sprintf(`{"runtime":{"labels":{"note":%q}},"command":{"command_path":".agentarea/commands/command.sh"}}`, canary),
		fmt.Sprintf(`{"command":{"command_path":".agentarea/commands/command.sh","args":[%q]}}`, canary),
		fmt.Sprintf(`{"command":{"command_path":".agentarea/commands/command.sh","env":{"CANARY":%q}}}`, canary),
		fmt.Sprintf(`{"command":{"command_path":".agentarea/commands/command.sh","script":%q}}`, canary),
	}
	for _, payload := range payloads {
		var request ExecutionCreateRequest
		err := json.Unmarshal([]byte(payload), &request)
		if err == nil || !strings.Contains(err.Error(), "unsupported_contract_version") {
			t.Fatalf("caller-controlled body channel accepted: %s; error = %v", payload, err)
		}
	}
}

func TestRedisStoreRejectsNonInternalMetadata(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := NewRedisStore("redis://"+server.Addr(), "agentarea:sandbox", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	record := validStoredExecutionRecord()
	record.Metadata = map[string]string{"caller_note": "REDIS-METADATA-CANARY"}
	if err := store.CreateExecution(context.Background(), record); err == nil || !strings.Contains(err.Error(), "metadata") {
		t.Fatalf("CreateExecution() error = %v, want rejected metadata", err)
	}
	if server.Exists("agentarea:sandbox:execution:" + record.ID) {
		t.Fatal("record with caller metadata was persisted")
	}
}

func TestRedisStoreAcceptsAllowlistedRunnerMetadata(t *testing.T) {
	server := miniredis.RunT(t)
	store, err := NewRedisStore("redis://"+server.Addr(), "agentarea:sandbox", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	record := validStoredExecutionRecord()
	record.Metadata = map[string]string{
		"runner_consumer": "runner-1",
		"runner_phase":    "workspace_commit_pending",
	}
	if err := store.CreateExecution(context.Background(), record); err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
}

func validStoredExecutionRecord() *ExecutionRecord {
	ref := validTestManifestRef("workspace-1", "task-1", "d", 1, 13)
	now := time.Now().UTC()
	return &ExecutionRecord{
		ID:                   "sexec-test-1",
		WorkflowID:           "workflow-1",
		TaskID:               ref.TaskID,
		WorkspaceID:          ref.WorkspaceID,
		Runtime:              RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		Status:               ExecutionStatusQueued,
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
		WorkspaceManifestRef: ref,
		CreatedAt:            now,
		UpdatedAt:            now,
	}
}

func TestRedisTransportRefsOnlyCanary(t *testing.T) {
	server := miniredis.RunT(t)
	ctx := context.Background()
	store, err := NewRedisStore("redis://"+server.Addr(), "agentarea:sandbox", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	events := NewRedisEventBus(store.RedisClient(), "test.requests", "test.events", "test")
	service := NewService(store, events)
	pubsub := store.RedisClient().Subscribe(ctx, "test.requests", "test.events")
	defer pubsub.Close()
	if _, err := pubsub.Receive(ctx); err != nil {
		t.Fatal(err)
	}
	pubsubMessages := pubsub.Channel()

	canary := []byte("UNIQUE-WORKSPACE-FILE-CANARY-DO-NOT-TRANSPORT")
	first := createRefsOnlyExecution(t, ctx, service, canary, 1024, 1)
	firstRaw := rawExecutionTransport(t, ctx, store.RedisClient(), first.ID, "test.requests", "test.events")
	firstRaw = append(firstRaw, readPubSubTransport(t, pubsubMessages, first.ID, 2)...)
	second := createRefsOnlyExecution(t, ctx, service, canary, 32*1024*1024, 2)
	secondRaw := rawExecutionTransport(t, ctx, store.RedisClient(), second.ID, "test.requests", "test.events")
	secondRaw = append(secondRaw, readPubSubTransport(t, pubsubMessages, second.ID, 2)...)

	combined := append(append([]byte{}, firstRaw...), secondRaw...)
	for _, forbidden := range [][]byte{
		canary,
		[]byte(base64.StdEncoding.EncodeToString(canary)),
		[]byte("content_base64"),
		[]byte("input_files"),
		[]byte("script_content"),
		[]byte("script_name"),
		[]byte("X-Amz-Signature"),
		[]byte("AWS_ACCESS_KEY_ID"),
		[]byte("AWS_SECRET_ACCESS_KEY"),
	} {
		if strings.Contains(string(combined), string(forbidden)) {
			t.Fatalf("raw Redis transport contains forbidden material %q", forbidden)
		}
	}
	delta := len(secondRaw) - len(firstRaw)
	if delta < 0 {
		delta = -delta
	}
	if delta > 4096 {
		t.Fatalf("Redis payload growth delta = %d, want <= 4096", delta)
	}
}

func readPubSubTransport(t *testing.T, messages <-chan *redis.Message, executionID string, expected int) []byte {
	t.Helper()
	timer := time.NewTimer(time.Second)
	defer timer.Stop()
	raw := make([]byte, 0)
	matched := 0
	for matched < expected {
		select {
		case message := <-messages:
			if message != nil && strings.Contains(message.Payload, executionID) {
				raw = append(raw, []byte(message.Payload)...)
				matched++
			}
		case <-timer.C:
			t.Fatalf("received %d/%d PubSub events for execution %s", matched, expected, executionID)
		}
	}
	return raw
}

func createRefsOnlyExecution(t *testing.T, ctx context.Context, service *Service, canary []byte, objectSize, generation int64) *ExecutionRecord {
	t.Helper()
	hash := sha256.Sum256(append(append([]byte{}, canary...), byte(generation)))
	digest := hex.EncodeToString(hash[:])
	ref := &workspace.ManifestRef{
		SchemaVersion:  workspace.SchemaVersion,
		WorkspaceID:    "workspace-canary",
		TaskID:         fmt.Sprintf("task-%d", generation),
		Generation:     generation,
		ManifestURI:    fmt.Sprintf("s3://trusted/workspaces/workspace-canary/tasks/task-%d/manifests/%d-%s.json", generation, generation, digest),
		ManifestSHA256: digest,
		BaseGeneration: generation - 1,
		FencingToken:   generation,
	}
	record, err := service.CreateExecution(ctx, ExecutionCreateRequest{
		Runtime:              RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		TaskID:               ref.TaskID,
		WorkspaceID:          ref.WorkspaceID,
		WorkspaceManifestRef: ref,
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
	next := *ref
	next.BaseGeneration = ref.Generation
	next.Generation++
	next.ManifestURI = fmt.Sprintf("s3://trusted/workspaces/workspace-canary/tasks/task-%d/manifests/%d-%s.json", generation, next.Generation, digest)
	updated, err := service.ApplyExecutionEvent(ctx, record.ID, ExecutionEventRequest{
		EventType:            EventTypeExecutionCompleted,
		WorkspaceManifestRef: &next,
		OutputRefs: []SandboxObjectReference{{
			RelativePath:        "reports/result.bin",
			ObjectURI:           fmt.Sprintf("s3://trusted/workspaces/workspace-canary/tasks/task-%d/objects/%s", generation, digest),
			ObjectVersionOrETag: "etag-immutable",
			SHA256:              digest,
			Size:                objectSize,
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	return updated
}

func rawExecutionTransport(t *testing.T, ctx context.Context, client *redis.Client, executionID string, streams ...string) []byte {
	t.Helper()
	record, err := client.Get(ctx, "agentarea:sandbox:execution:"+executionID).Bytes()
	if err != nil {
		t.Fatal(err)
	}
	raw := append([]byte{}, record...)
	for _, stream := range streams {
		messages, err := client.XRange(ctx, stream, "-", "+").Result()
		if err != nil {
			t.Fatal(err)
		}
		for _, message := range messages {
			if strings.Contains(fmt.Sprint(message.Values["event"]), executionID) {
				raw = append(raw, []byte(fmt.Sprint(message.Values["event"]))...)
			}
		}
	}
	return raw
}
