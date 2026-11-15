// Package replies is the delivery group on tasks.events (ADR-0043 §7): each task event goes to
// where its task replies — the chat or mailbox it came from (its delivery address) and the
// caller's task webhook — through the sender the target names (http, telegram_live, smtp,
// task_webhook). A target is marked delivered only after its send succeeded; the message is
// acknowledged once every target is delivered or dead-lettered.
package replies

import (
	"errors"
	"fmt"
	"strings"

	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// Presentation modes of a target.
const (
	Verbose = "verbose"
	Concise = "concise"
	Summary = "summary"
	Silent  = "silent"
)

const (
	// AddressTarget is the key of the target a task's delivery address makes.
	AddressTarget = "address"
	// TaskWebhookTarget is the key and sender of the caller's task webhook.
	TaskWebhookTarget = "task_webhook"
	// TargetField names the one target a dead letter is for; a replay of it sends there only.
	TargetField = "delivery_target"

	deliveryAddressParameter = "delivery_address"
	taskWebhookKey           = "task_webhook"
)

// Target is one place a task's events go, under a key stable for the task.
type Target struct {
	Key          string
	Sender       string
	Config       map[string]any
	Presentation string
	// Data is what the target adds to the event data it is sent.
	Data map[string]any
}

// Fatal is a send no retry can make: the target is dead-lettered at once.
type Fatal struct{ Msg string }

func (e *Fatal) Error() string { return e.Msg }

func fatalf(format string, a ...any) error { return &Fatal{Msg: fmt.Sprintf(format, a...)} }

// IsFatal reports whether err is a Fatal.
func IsFatal(err error) bool {
	var f *Fatal
	return errors.As(err, &f)
}

// Targets is delivery_targets: the task's delivery address and its task webhook. A delivery
// address without type or sender is logged by the caller and left out.
func Targets(task runsapi.OutcomeTask) ([]Target, []string) {
	var out []Target
	var malformed []string
	if address, ok := task.Parameters[deliveryAddressParameter].(map[string]any); ok {
		sender, _ := address["sender"].(string)
		kind, _ := address["type"].(string)
		if sender != "" && kind != "" {
			presentation, _ := address["presentation"].(string)
			if presentation == "" {
				presentation = Concise
			}
			out = append(out, Target{Key: AddressTarget, Sender: sender, Config: address, Presentation: presentation})
		} else {
			malformed = append(malformed, fmt.Sprintf("delivery address without type or sender: %v", address))
		}
	}
	if webhook, ok := task.Metadata[taskWebhookKey].(map[string]any); ok {
		if url, _ := webhook["url"].(string); url != "" {
			signed, _ := webhook["signed"].(bool)
			out = append(out, Target{
				Key: TaskWebhookTarget, Sender: TaskWebhookTarget, Presentation: Silent,
				Config: map[string]any{"type": TaskWebhookTarget, "url": url, "signed": signed, "presentation": Silent},
				Data:   map[string]any{"end_user_id": task.Metadata["end_user_id"], "app_metadata": task.Metadata["app_metadata"]},
			})
		}
	}
	return out, malformed
}

// CanonicalType strips the workflow. prefix an older publisher put on the wire.
func CanonicalType(t string) string { return strings.TrimPrefix(t, "workflow.") }

// Visible is is_visible: whether a target of presentation shows an event of type t; an unknown
// presentation shows what concise shows.
func Visible(t, presentation string) bool {
	t = CanonicalType(t)
	switch t {
	case "task.completed", "task.failed", "task.cancelled":
		return true
	case "approval.requested", "approval.decided", "input.request", "input.response":
		return presentation != Silent
	case "task.started", "command.received", "tool.call", "delegation.started", "delegation.completed":
		return presentation == Verbose || (presentation != Summary && presentation != Silent)
	case "llm.call.started", "llm.call.chunk", "llm.call.completed", "llm.call.failed", "tool.result",
		"turn.completed", "context.compacted", "budget.warning", "budget.exceeded":
		return presentation == Verbose
	}
	return false
}
