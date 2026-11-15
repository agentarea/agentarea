package router

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/service"
)

// Processor run limits (domain/processor.py).
const (
	ProcessorTimeout     = 10 * time.Second
	MaxResultBytes       = 256 * 1024
	MaxOutputs           = 100
	MaxCommandBytes      = 256 * 1024
	TimedOutExit         = 124
	maxReasonChars       = 1000
	harnessDelimiter     = "AGENTAREA_PROCESSOR_HARNESS"
	processorTimeoutSecs = 10
)

const harness = `import base64, json, sys, traceback
code = base64.b64decode("__CODE__").decode()
event = json.loads(base64.b64decode("__EVENT__"))
result = sys.stdout
sys.stdout = sys.stderr
def failure(error):
    frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == "processor.py"]
    where = f" (processor.py line {frames[-1].lineno})" if frames else ""
    return {"ok": False, "error": f"{type(error).__name__}: {error}{where}"}
try:
    scope = {"__name__": "processor"}
    exec(compile(code, "processor.py", "exec"), scope)
    text = json.dumps({"ok": True, "outputs": scope["process"](event)})
except BaseException as error:
    text = json.dumps(failure(error))
result.write(text)
result.flush()
`

// ProcessorFailed is ProcessorFailedError: the run gave no usable result, an error reaction.
type ProcessorFailed struct{ Reason string }

func (e *ProcessorFailed) Error() string { return e.Reason }

func failed(format string, args ...any) error {
	return &ProcessorFailed{Reason: fmt.Sprintf(format, args...)}
}

// ProcessorOutput is one event process() returned: {stream, kind, data, key?}.
type ProcessorOutput struct {
	Stream string
	Kind   string
	Data   map[string]any
	Key    *string
}

// SandboxSession is the sandbox session every run of one processor shares.
func SandboxSession(processorID string) string { return "processor-" + processorID }

func marshal(v any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(b.Bytes(), "\n"), nil
}

func optional(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

// EventPayload is event_payload, encoded with its keys in Python's order.
func EventPayload(e domain.Event) ([]byte, error) {
	attachments := e.Attachments
	if attachments == nil {
		attachments = []domain.Attachment{}
	}
	data := e.Data
	if data == nil {
		data = map[string]any{}
	}
	fields := []struct {
		k string
		v any
	}{
		{"id", e.ID}, {"kind", e.Kind}, {"source", e.Source}, {"subject", optional(e.Subject)},
		{"time", events.PyISO(e.OccurredAt)}, {"received_at", events.PyISO(e.ReceivedAt)},
		{"stream_id", e.StreamID}, {"key", e.EventKey}, {"source_type", optional(e.SourceType)},
		{"session_key", optional(e.SessionKey)}, {"sender", optional(e.Sender)},
		{"correlation_id", optional(e.CorrelationID)}, {"causation_id", optional(e.CausationID)},
		{"depth", e.Depth}, {"data", data}, {"attachments", attachments},
	}
	var b bytes.Buffer
	b.WriteByte('{')
	for i, f := range fields {
		if i > 0 {
			b.WriteByte(',')
		}
		k, _ := marshal(f.k)
		v, err := marshal(f.v)
		if err != nil {
			return nil, err
		}
		b.Write(k)
		b.WriteByte(':')
		b.Write(v)
	}
	b.WriteByte('}')
	return b.Bytes(), nil
}

// HarnessCommand is harness_command: the bash command that runs process over the payload.
func HarnessCommand(code string, payload []byte) (string, error) {
	script := strings.Replace(harness, "__CODE__", base64.StdEncoding.EncodeToString([]byte(code)), 1)
	script = strings.Replace(script, "__EVENT__", base64.StdEncoding.EncodeToString(payload), 1)
	command := "python3 - <<'" + harnessDelimiter + "'\n" + script + harnessDelimiter + "\n"
	if len(command) > MaxCommandBytes {
		return "", failed("The event is too large for a processor: %d bytes of event and %d of code exceed %d bytes once encoded",
			len(payload), len(code), MaxCommandBytes)
	}
	return command, nil
}

func clip(text string) string {
	if utf8.RuneCountInString(text) <= maxReasonChars {
		return text
	}
	return string([]rune(text)[:maxReasonChars-1]) + "…"
}

func lastRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[len(r)-n:])
}

func jsonType(v any) string {
	switch v.(type) {
	case map[string]any:
		return "an object"
	case string:
		return "a string"
	case bool:
		return "a boolean"
	case json.Number:
		return "a number"
	}
	return "a value"
}

func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return x
	}
	b, err := marshal(v)
	if err != nil {
		return fmt.Sprint(v)
	}
	return string(b)
}

// OutputsOf is outputs_of: the events one run wrote; a *ProcessorFailed when the run is no usable result.
func OutputsOf(run service.CodeRun) ([]ProcessorOutput, error) {
	if run.ExitCode == TimedOutExit {
		return nil, failed("process() did not finish within %ds", processorTimeoutSecs)
	}
	if run.StdoutTruncated {
		return nil, failed("process() returned more than %d bytes", MaxResultBytes)
	}
	if run.ExitCode != 0 {
		msg := fmt.Sprintf("The processor exited with code %d", run.ExitCode)
		if tail := lastRunes(strings.Join(strings.Fields(run.Stderr), " "), 300); tail != "" {
			msg += ": " + tail
		}
		return nil, failed("%s", clip(msg))
	}
	var result map[string]any
	dec := json.NewDecoder(strings.NewReader(run.Stdout))
	dec.UseNumber()
	if err := dec.Decode(&result); err != nil || dec.More() {
		result = nil
	}
	ok, isBool := result["ok"].(bool)
	if result == nil || !isBool {
		return nil, failed("The processor printed no result")
	}
	if !ok {
		return nil, failed("%s", clip(pyStr(result["error"])))
	}
	raw, present := result["outputs"]
	if !present || raw == nil {
		return []ProcessorOutput{}, nil
	}
	items, isList := raw.([]any)
	if !isList {
		return nil, failed("process() must return a list of events or None, not %s", jsonType(raw))
	}
	if len(items) > MaxOutputs {
		return nil, failed("process() returned more than %d events", MaxOutputs)
	}
	out := make([]ProcessorOutput, 0, len(items))
	for i, item := range items {
		o, problem := parseOutput(item)
		if problem != "" {
			return nil, failed("%s", clip(fmt.Sprintf("event %d is not {stream, kind, data, key?}: %s", i, problem)))
		}
		out = append(out, o)
	}
	return out, nil
}

func textField(m map[string]any, name string, most int, required bool) (*string, string) {
	v, present := m[name]
	if !present {
		if required {
			return nil, name + ": Field required"
		}
		return nil, ""
	}
	if v == nil && !required {
		return nil, ""
	}
	s, ok := v.(string)
	if !ok {
		return nil, name + ": Input should be a valid string"
	}
	n := utf8.RuneCountInString(s)
	if n < 1 {
		return nil, name + ": String should have at least 1 character"
	}
	if n > most {
		return nil, fmt.Sprintf("%s: String should have at most %d characters", name, most)
	}
	return &s, ""
}

// parseOutput is ProcessorOutput.model_validate (strict, extra forbidden): the first problem in field order.
func parseOutput(item any) (ProcessorOutput, string) {
	m, ok := item.(map[string]any)
	if !ok {
		return ProcessorOutput{}, "Input should be a valid dictionary or instance of ProcessorOutput"
	}
	var o ProcessorOutput
	stream, problem := textField(m, "stream", 255, true)
	if problem != "" {
		return o, problem
	}
	kind, problem := textField(m, "kind", 255, true)
	if problem != "" {
		return o, problem
	}
	d, present := m["data"]
	if !present {
		return o, "data: Field required"
	}
	data, isMap := d.(map[string]any)
	if !isMap {
		return o, "data: Input should be a valid dictionary"
	}
	key, problem := textField(m, "key", 512, false)
	if problem != "" {
		return o, problem
	}
	var extra []string
	for k := range m {
		switch k {
		case "stream", "kind", "data", "key":
		default:
			extra = append(extra, k)
		}
	}
	if len(extra) > 0 {
		sort.Strings(extra)
		return o, extra[0] + ": Extra inputs are not permitted"
	}
	return ProcessorOutput{Stream: *stream, Kind: *kind, Data: data, Key: key}, ""
}

func pyRepr(s string) string {
	q := "'"
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		q = `"`
	}
	s = strings.ReplaceAll(s, `\`, `\\`)
	if q == "'" {
		s = strings.ReplaceAll(s, "'", `\'`)
	}
	return q + s + q
}

// Routed is an output with the declared stream it names.
type Routed struct {
	StreamID string
	Output   ProcessorOutput
}

// ResolveStreams is resolve_streams: each output with the declared stream it names, by id or by name.
func ResolveStreams(outputs []ProcessorOutput, declared map[string]string, inputStreamID string) ([]Routed, error) {
	byName := make(map[string]string, len(declared))
	names := make([]string, 0, len(declared))
	for id, name := range declared {
		byName[name] = id
		names = append(names, name)
	}
	sort.Strings(names)
	routed := make([]Routed, 0, len(outputs))
	for i, o := range outputs {
		id := ""
		if _, ok := declared[o.Stream]; ok {
			id = o.Stream
		} else if n, ok := byName[o.Stream]; ok {
			id = n
		}
		if id == inputStreamID || o.Stream == inputStreamID {
			return nil, failed("event %d names the processor's own input stream; a processor never writes to its own input", i)
		}
		if id == "" {
			list := strings.Join(names, ", ")
			if list == "" {
				list = "none"
			}
			return nil, failed("%s", clip(fmt.Sprintf("event %d names stream %s, which is not one of this processor's outputs (%s)",
				i, pyRepr(o.Stream), list)))
		}
		routed = append(routed, Routed{StreamID: id, Output: o})
	}
	return routed, nil
}

func asFailed(err error) (*ProcessorFailed, bool) {
	var f *ProcessorFailed
	return f, errors.As(err, &f)
}
