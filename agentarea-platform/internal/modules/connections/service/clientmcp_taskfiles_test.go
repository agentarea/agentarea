package service

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mcpserve"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/mcpserver"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

type signedTaskFiles struct{ asked []string }

func (s *signedTaskFiles) TaskFileURLs(_ context.Context, _ scope.Workspace, taskID, path string) ([]runsapi.TaskFileURL, error) {
	s.asked = append(s.asked, taskID+":"+path)
	if path != "inputs/attachments/IMG.MOV" {
		return nil, runsapi.ErrNoTaskFile
	}
	return []runsapi.TaskFileURL{{Path: path, URL: "https://s3.test/signed", SHA256: "ab", Size: 5, ExpiresInSeconds: 300}}, nil
}

func TestARunnersTurnGetsDownloadURLsOfItsTasksFiles(t *testing.T) {
	f := newClientFixture(t, nil)
	files := &signedTaskFiles{}
	f.svc.UseTaskFiles(files)
	turn := f.backend(t, authn.Principal{UserID: "u1", BoundTaskID: "child-task", TurnClientID: f.clientID, AccessibleWorkspaces: []string{clientWS}})
	tools, err := turn.ListTools(context.Background())
	if err != nil || !hasTool(tools, DownloadURLTool) {
		t.Fatalf("a turn's tools %v %v", tools, err)
	}
	out, err := turn.CallTool(context.Background(), DownloadURLTool, json.RawMessage(`{"path":"inputs/attachments/IMG.MOV"}`))
	if err != nil {
		t.Fatal(err)
	}
	res := out.(mcpserve.Result)
	if res.IsError || !strings.Contains(res.Content[0].Text, "https://s3.test/signed") || !strings.Contains(res.Content[0].Text, "expires in 300s") {
		t.Fatalf("result %+v", res)
	}
	out, _ = turn.CallTool(context.Background(), DownloadURLTool, json.RawMessage(`{"path":"inputs/none"}`))
	if res := out.(mcpserve.Result); !res.IsError {
		t.Fatalf("a missing file answered %+v", res)
	}
	if len(files.asked) != 2 || files.asked[0] != "child-task:inputs/attachments/IMG.MOV" {
		t.Fatalf("asked %v", files.asked)
	}

	member, err := f.backend(t, workspaceMember()).ListTools(context.Background())
	if err != nil || hasTool(member, DownloadURLTool) {
		t.Fatalf("a caller outside a turn was offered task files: %v", err)
	}
}

func hasTool(tools []mcpserver.Tool, name string) bool {
	for _, t := range tools {
		if t.Name == name {
			return true
		}
	}
	return false
}
