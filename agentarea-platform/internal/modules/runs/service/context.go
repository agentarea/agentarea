package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// StoreOutput keeps a tool output too long for the conversation in a file of
// the task whose files the run works on (filesTaskID; "" is taskID's own) and
// returns its path, which read_file and the shell read.
func (s *Service) StoreOutput(ctx context.Context, p Principal, taskID, filesTaskID, workflowID, outputID, content string) (string, error) {
	if _, err := workspace(p); err != nil {
		return "", err
	}
	return s.keepToolOutput(ctx, p, taskID, firstOf(filesTaskID, taskID), workflowID, outputID, content)
}

func (s *Service) keepToolOutput(ctx context.Context, p Principal, taskID, filesTask, workflowID, outputID, content string) (string, error) {
	if s.d.Workspace == nil {
		return "", errors.New("a tool output cannot be kept: this deployment has no task workspace")
	}
	if !domain.IsOutputID(outputID) {
		return "", fmt.Errorf("%q cannot name a tool output file", outputID)
	}
	path := domain.ToolOutputPath(outputID, content)
	contentType := "text/plain; charset=utf-8"
	if strings.HasSuffix(path, ".json") {
		contentType = "application/json"
	}
	file := sandboxapi.WorkspaceFile{Path: path, Data: []byte(content), ContentType: contentType}
	opts := sandboxapi.WriteOptions{Owner: workflowID, Actor: agentActor(p, taskID)}
	if _, err := s.d.Workspace.PutFiles(ctx, p.WorkspaceID, filesTask, []sandboxapi.WorkspaceFile{file}, opts); err != nil {
		return "", err
	}
	return path, nil
}

// agentActor is the agent of a run writing into its task workspace.
func agentActor(p Principal, taskID string) *sandboxapi.Actor {
	actor := &sandboxapi.Actor{UserID: p.UserID, ActorType: "agent", TaskID: &taskID}
	if p.AgentID != "" {
		actor.AgentID = &p.AgentID
	}
	return actor
}

type historyMessage struct {
	Role       string `json:"role"`
	Content    string `json:"content"`
	ToolCalls  []any  `json:"tool_calls,omitempty"`
	ToolCallID string `json:"tool_call_id,omitempty"`
	Name       string `json:"name,omitempty"`
}

// StoreHistoryChunk keeps the messages a compaction replaced, for search_history.
func (s *Service) StoreHistoryChunk(ctx context.Context, p Principal, taskID string, index int, messages []domain.ChatMessage) error {
	out := make([]historyMessage, 0, len(messages))
	for _, m := range messages {
		var calls []any
		if len(m.ToolCalls) > 0 {
			calls = domain.ToolCallsJSON(m.ToolCalls)
		}
		out = append(out, historyMessage{Role: m.Role, Content: m.Content, ToolCalls: calls, ToolCallID: m.ToolCallID, Name: m.Name})
	}
	body, err := json.Marshal(out)
	if err != nil {
		return err
	}
	return s.putText(ctx, domain.HistoryChunkKey(p.WorkspaceID, taskID, index), string(body), "application/json")
}

// SearchHistory greps the stored history chunks; a failure is reported in the text.
func (s *Service) SearchHistory(ctx context.Context, p Principal, taskID, grep, toolName string) (string, error) {
	if _, err := workspace(p); err != nil {
		return "", err
	}
	var found []string
	for info, err := range s.d.Blob.List(ctx, domain.HistoryPrefix(p.WorkspaceID, taskID)) {
		if err != nil {
			return "Error searching history: " + err.Error(), nil
		}
		if len(found) >= domain.HistorySearchMaxResult {
			break
		}
		body, err := s.getText(ctx, info.Key)
		if err != nil {
			return "Error searching history: " + err.Error(), nil
		}
		var chunk []domain.HistoryMessage
		if err := json.Unmarshal([]byte(body), &chunk); err != nil {
			return "Error searching history: " + err.Error(), nil
		}
		found = domain.HistoryMatches(chunk, grep, toolName, found)
	}
	return domain.HistorySearchResult(found), nil
}

// FeedItem is a task feed row as recall_history returns it.
type FeedItem struct {
	Seq       int64
	Type      string
	Data      map[string]any
	Timestamp time.Time
}

// Recall is the answer of recall_history.
type Recall struct {
	Events  []FeedItem
	Total   int
	Summary string
}

// RecallHistory reads the task's own feed rows of the given types, newest
// first; a type outside the vocabulary is refused with the valid ones.
func (s *Service) RecallHistory(ctx context.Context, p Principal, taskID string, types []string, limit int) (Recall, error) {
	ws, err := workspace(p)
	if err != nil {
		return Recall{}, err
	}
	var unknown []string
	for _, t := range types {
		if !domain.Recallable(t) {
			unknown = append(unknown, t)
		}
	}
	if len(unknown) > 0 {
		return Recall{Summary: fmt.Sprintf("Unknown event types %s. Event types are dotted, one of: %s", domain.PyListRepr(unknown), strings.Join(recallableTypes(), ", "))}, nil
	}
	var entries []domain.Entry
	err = s.readSession(ctx, ws, func(tx db.Session) error {
		var err error
		entries, err = s.store.LatestFeed(ctx, tx, taskID, types, limit)
		return err
	})
	if err != nil {
		s.d.Log.ErrorContext(ctx, "recall history failed", "task_id", taskID, "error", err)
		return Recall{Summary: "Failed to recall history: " + err.Error()}, nil
	}
	var items []FeedItem
	counts := map[string]int{}
	var order []string
	for _, e := range entries {
		t, data, ok := domain.FeedEvent(e, nil)
		if !ok {
			continue
		}
		item := FeedItem{Seq: e.Seq, Type: t, Data: data}
		if e.OccurredAt != nil {
			item.Timestamp = *e.OccurredAt
		}
		items = append(items, item)
		if counts[t] == 0 {
			order = append(order, t)
		}
		counts[t]++
	}
	parts := make([]string, 0, len(order))
	for _, t := range order {
		parts = append(parts, fmt.Sprintf("%dx %s", counts[t], t))
	}
	return Recall{Events: items, Total: len(items), Summary: fmt.Sprintf("Retrieved %d events: %s", len(items), strings.Join(parts, ", "))}, nil
}

func recallableTypes() []string {
	var out []string
	for _, t := range allEventTypes() {
		if domain.Recallable(t) {
			out = append(out, t)
		}
	}
	slices.Sort(out)
	return out
}

func allEventTypes() []string {
	return []string{
		domain.EventLLMStarted, domain.EventLLMCompleted, domain.EventLLMFailed, domain.EventLLMChunk,
		domain.EventToolCall, domain.EventToolResult, domain.EventToolProgress, domain.EventInputRequest,
		domain.EventInputResponse, domain.EventApprovalRequested, domain.EventApprovalDecided,
		domain.EventArtifactCreated, domain.EventArtifactUpdated, domain.EventA2UICreate,
		domain.EventA2UIUpdateComponents, domain.EventA2UIUpdateData, domain.EventA2UIDelete,
		domain.EventTaskStarted, domain.EventTaskCompleted, domain.EventTaskFailed, domain.EventTaskCancelled,
		domain.EventTaskAwaitingFollowUp, domain.EventTaskAwaitingContinuation, domain.EventTaskContinued,
		domain.EventTaskAwaitingInfra, domain.EventTaskInfraRecovered, domain.EventSkillWithheld,
		domain.EventTaskRetried, domain.EventExecutionFinished, domain.EventExecutionContinuedAsNew,
		domain.EventExecutionPaused, domain.EventExecutionResumed, domain.EventArtifactValidationStarted,
		domain.EventArtifactValidationDone, domain.EventTurnStarted, domain.EventTurnCompleted,
		domain.EventTurnAborted, domain.EventBudgetWarning, domain.EventBudgetExceeded, domain.EventBudgetUpdated,
		domain.EventServicePayment, domain.EventServiceBudgetWarning, domain.EventServiceBudgetExceeded,
		domain.EventContextCompacted, domain.EventContextWarning, domain.EventAnswerChecked,
		domain.EventModelChanged, domain.EventModelFallback, domain.EventModelUnavailable,
		domain.EventRuntimeDiscovered, domain.EventCommandReceived, domain.EventCommandRejected,
		domain.EventMessageQueued, domain.EventMessageReceived, domain.EventMessageRemoved,
		domain.EventInputSubmitted, domain.EventDelegationStarted, domain.EventDelegationCompleted,
		domain.EventDelegationFailed,
	}
}

// readSession runs fn on a read session of the workspace.
func (s *Service) readSession(ctx context.Context, ws scope.Workspace, fn func(tx db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}
