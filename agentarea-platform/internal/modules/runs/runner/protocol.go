// Package runner is a harness client's runner on the platform (ADR-0051):
// its one outbound socket for turns, who it is, and the files its CLI made
// (apps/api/.../v1/harness_runner.py, agentarea_tasks/harness_protocol.py).
package runner

import (
	"bytes"
	"encoding/json"
	"fmt"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/workflows"
)

const (
	pingSeconds  = 10
	leaseSeconds = 30
	lease        = leaseSeconds * time.Second
	helloTimeout = 30 * time.Second
	// heartbeatEvery is how often a held turn heartbeats and renews its token's lease.
	heartbeatEvery = 2 * time.Second
	updateEvery    = time.Second
	deliveryPoll   = 5 * time.Second
	signalMaxChars = 500_000
	finalAttempts  = 5
	stopGrace      = 15 * time.Second
	toolOutputMax  = 32_000
	frameMaxChars  = 1_000_000
	turnPendingMax = 2_000
	turnTimeout    = 12 * time.Hour
	// fileMaxBytes is the largest file a runner uploads.
	fileMaxBytes = 50 * 1024 * 1024

	snapshotInterval = 100 * time.Millisecond
	progressInterval = 500 * time.Millisecond
	progressTailChar = 4000

	clippedNote = "\n…[output clipped; the full files are the task's]"
)

// protocolError is a frame the runner may not send: the socket closes 1003.
type protocolError struct{ msg string }

func (e *protocolError) Error() string { return e.msg }

func badFrame(format string, args ...any) error {
	return &protocolError{msg: fmt.Sprintf(format, args...)}
}

type reportedModel struct {
	Name             *string   `json:"name"`
	ReasoningLevels  *[]string `json:"reasoning_levels"`
	DefaultReasoning *string   `json:"default_reasoning"`
}

// upFrame is any frame a runner sends; parse checks the fields its type needs.
type upFrame struct {
	Type string `json:"type"`

	Models       *[]reportedModel `json:"models"`
	DefaultModel *string          `json:"default_model"`
	Capacity     *int             `json:"capacity"`
	Version      *string          `json:"version"`
	Turns        []string         `json:"turns"`

	TurnID    *string         `json:"turn_id"`
	SessionID *string         `json:"session_id"`
	Seq       *int64          `json:"seq"`
	Event     json.RawMessage `json:"event"`

	RequestID *string         `json:"request_id"`
	ItemID    *string         `json:"item_id"`
	Kind      *string         `json:"kind"`
	ToolName  *string         `json:"tool_name"`
	Arguments json.RawMessage `json:"arguments"`
	Reason    *string         `json:"reason"`

	MessageID *string `json:"message_id"`

	Status   *string `json:"status"`
	Response *string `json:"response"`
	Error    *string `json:"error"`

	body eventBody
	args map[string]any
}

// eventBody is a turn.event's event, discriminated on kind.
type eventBody struct {
	Kind      string          `json:"kind"`
	ItemID    *string         `json:"item_id"`
	ID        *string         `json:"id"`
	Name      *string         `json:"name"`
	Text      *string         `json:"text"`
	Channel   *string         `json:"channel"`
	Model     *string         `json:"model"`
	Arguments json.RawMessage `json:"arguments"`
	Output    *string         `json:"output"`
	Success   *bool           `json:"success"`
	ExitCode  *int            `json:"exit_code"`

	args map[string]any
}

func required[T any](field string, v *T) error {
	if v == nil {
		return badFrame("%s is required", field)
	}
	return nil
}

func objectOrEmpty(field string, raw json.RawMessage) (map[string]any, error) {
	if len(raw) == 0 {
		return map[string]any{}, nil
	}
	var m map[string]any
	if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) || json.Unmarshal(raw, &m) != nil {
		return nil, badFrame("%s must be an object", field)
	}
	return m, nil
}

func validUUID(field string, v *string) error {
	if err := required(field, v); err != nil {
		return err
	}
	if _, err := uuid.Parse(*v); err != nil {
		return badFrame("%s is not a UUID", field)
	}
	return nil
}

// parseUpFrame is parse_up_frame: a frame from the runner, or a protocolError.
func parseUpFrame(raw []byte) (*upFrame, error) {
	if n := utf8.RuneCount(raw); n > frameMaxChars {
		return nil, badFrame("a frame of %d characters", n)
	}
	var f upFrame
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, badFrame("not a frame: %v", err)
	}
	var err error
	switch f.Type {
	case "hello":
		err = f.checkHello()
	case "ping":
	case "turn.started":
		if err = validUUID("turn_id", f.TurnID); err == nil {
			err = required("session_id", f.SessionID)
		}
	case "turn.event":
		err = f.checkEvent()
	case "approval.request":
		err = f.checkApproval()
	case "steer.accepted", "steer.rejected":
		if err = validUUID("turn_id", f.TurnID); err == nil {
			err = required("message_id", f.MessageID)
		}
	case "turn.finished":
		if err = validUUID("turn_id", f.TurnID); err == nil {
			err = required("status", f.Status)
		}
		if err == nil && *f.Status != "completed" && *f.Status != "failed" && *f.Status != "interrupted" {
			err = badFrame("status %q is not completed, failed or interrupted", *f.Status)
		}
	default:
		err = badFrame("unknown frame type %q", f.Type)
	}
	if err != nil {
		return nil, err
	}
	return &f, nil
}

func (f *upFrame) checkHello() error {
	if f.Capacity == nil {
		one := 1
		f.Capacity = &one
	}
	if *f.Capacity < 1 || *f.Capacity > 16 {
		return badFrame("capacity must be 1 to 16")
	}
	for _, t := range f.Turns {
		if _, err := uuid.Parse(t); err != nil {
			return badFrame("turns holds %q, not a UUID", t)
		}
	}
	if f.Models != nil {
		for _, m := range *f.Models {
			if m.Name == nil {
				return badFrame("a model has no name")
			}
		}
	}
	return nil
}

func (f *upFrame) checkEvent() error {
	if err := validUUID("turn_id", f.TurnID); err != nil {
		return err
	}
	if err := required("seq", f.Seq); err != nil {
		return err
	}
	if *f.Seq < 1 {
		return badFrame("seq must be at least 1")
	}
	if len(f.Event) == 0 || json.Unmarshal(f.Event, &f.body) != nil {
		return badFrame("event must be an object")
	}
	b := &f.body
	switch b.Kind {
	case "message.delta":
		if err := required("item_id", b.ItemID); err != nil {
			return err
		}
		if err := required("text", b.Text); err != nil {
			return err
		}
		if b.Channel != nil && *b.Channel != "text" && *b.Channel != "thinking" {
			return badFrame("channel %q is not text or thinking", *b.Channel)
		}
	case "message":
		if err := required("item_id", b.ItemID); err != nil {
			return err
		}
		return required("text", b.Text)
	case "tool.call":
		if err := required("id", b.ID); err != nil {
			return err
		}
		if err := required("name", b.Name); err != nil {
			return err
		}
		var err error
		b.args, err = objectOrEmpty("arguments", b.Arguments)
		return err
	case "tool.progress":
		if err := required("id", b.ID); err != nil {
			return err
		}
		if err := required("name", b.Name); err != nil {
			return err
		}
		return required("output", b.Output)
	case "tool.result":
		if err := required("id", b.ID); err != nil {
			return err
		}
		return required("name", b.Name)
	default:
		return badFrame("unknown event kind %q", b.Kind)
	}
	return nil
}

func (f *upFrame) checkApproval() error {
	if err := validUUID("turn_id", f.TurnID); err != nil {
		return err
	}
	if err := required("request_id", f.RequestID); err != nil {
		return err
	}
	if err := required("kind", f.Kind); err != nil {
		return err
	}
	switch *f.Kind {
	case "command", "file_change", "tool":
	default:
		return badFrame("approval kind %q is not command, file_change or tool", *f.Kind)
	}
	if err := required("tool_name", f.ToolName); err != nil {
		return err
	}
	var err error
	f.args, err = objectOrEmpty("arguments", f.Arguments)
	return err
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// clipped is _clipped: a tool's output as the task log keeps it.
func clipped(output string) string {
	if utf8.RuneCountInString(output) <= toolOutputMax {
		return output
	}
	return string([]rune(output)[:toolOutputMax]) + clippedNote
}

func tail(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	r := []rune(s)
	return string(r[len(r)-n:])
}

// signalBatch is signal_batch: the first of a turn's events one signal
// carries, at least one, at most signalMaxChars of JSON.
func signalBatch(events []workflows.RunnerTurnEvent) []workflows.RunnerTurnEvent {
	size := 0
	for i, e := range events {
		b, err := json.Marshal(e)
		if err != nil {
			size += signalMaxChars
		} else {
			size += len(b)
		}
		if i > 0 && size > signalMaxChars {
			return events[:i]
		}
	}
	return events
}

// liveSnapshots is LiveSnapshots: what a turn's live deltas add up to, and
// when each item may be broadcast again.
type liveSnapshots struct {
	now      func() time.Time
	text     map[string]string
	thinking map[string]string
	output   map[string]string
	sent     map[string]time.Time
}

func newLiveSnapshots(now func() time.Time) *liveSnapshots {
	return &liveSnapshots{now: now, text: map[string]string{}, thinking: map[string]string{},
		output: map[string]string{}, sent: map[string]time.Time{}}
}

func (l *liveSnapshots) addText(itemID, delta, channel string) (text, thinking string, due bool) {
	if channel == "thinking" {
		l.thinking[itemID] += delta
	} else {
		l.text[itemID] += delta
	}
	if !l.due("text\x00"+itemID, snapshotInterval) {
		return "", "", false
	}
	return l.text[itemID], l.thinking[itemID], true
}

func (l *liveSnapshots) addOutput(callID, delta string) (string, bool) {
	l.output[callID] = tail(l.output[callID]+delta, progressTailChar)
	if !l.due("output\x00"+callID, progressInterval) {
		return "", false
	}
	return l.output[callID], true
}

func (l *liveSnapshots) forget(itemID string) {
	delete(l.text, itemID)
	delete(l.thinking, itemID)
	delete(l.output, itemID)
	delete(l.sent, "text\x00"+itemID)
	delete(l.sent, "output\x00"+itemID)
}

func (l *liveSnapshots) due(key string, interval time.Duration) bool {
	now := l.now()
	if last, ok := l.sent[key]; ok && now.Sub(last) < interval {
		return false
	}
	l.sent[key] = now
	return true
}
