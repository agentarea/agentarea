package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"
)

const (
	a2aCardPath     = "/.well-known/agent-card.json"
	a2aCallTimeout  = 120 * time.Second
	a2aNoOutput     = "(No output from agent)"
	a2aJSONRPC      = "JSONRPC"
	a2aVersion10    = "1.0"
	a2aVersion03    = "0.3"
	a2aMaxAnswer    = 16 << 20
	a2aVersionField = "A2A-Version"
)

// a2aPolling is how long GetTask is polled for a task still running: under the tool activity's 120 s.
type a2aPolling struct{ every, budget time.Duration }

// CallRemoteAgent is A2AAgentTool.execute: the message sent to the delegate's A2A agent, the
// task it starts polled until it ends, its answer returned as the tool's.
func (s *Service) CallRemoteAgent(ctx context.Context, call api.RemoteAgentCall) (api.RemoteAgentResult, error) {
	return s.callRemoteAgent(ctx, call, a2aPolling{every: 2 * time.Second, budget: 110 * time.Second})
}

func (s *Service) callRemoteAgent(ctx context.Context, call api.RemoteAgentCall, poll a2aPolling) (api.RemoteAgentResult, error) {
	ws, err := scope.NewWorkspace(call.WorkspaceID, "")
	if err != nil {
		return api.RemoteAgentResult{}, err
	}
	if s.d.Out == nil {
		return api.RemoteAgentResult{}, errors.New("calling a remote delegate needs the outbound clients")
	}
	if call.Message == "" {
		return raisedResult("message is required"), nil
	}
	token := ""
	if call.AuthSecretName != "" {
		if token, err = s.delegateToken(ctx, ws, call.UserID, call.AuthSecretName); err != nil {
			return raisedResult(fmt.Sprintf("Could not resolve the credential for '%s': %v", call.AgentName, err)), nil
		}
	}
	pay := s.paying(ws, call.UserID, call.AgentID, call.ToolName, call.ToolCallID, call.Paid)
	out := s.d.Out.Transport(netguard.Member)
	noRedirect := func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	d := remoteDelegate{
		name: call.AgentName, address: call.A2AURL, token: token, poll: poll,
		card: &http.Client{Transport: out, Timeout: a2aCallTimeout, CheckRedirect: noRedirect},
		rpc:  &http.Client{Transport: pay.Wrap(out), Timeout: a2aCallTimeout, CheckRedirect: noRedirect},
	}
	res := d.delegate(ctx, call.Message)
	if err := ctx.Err(); err != nil {
		return api.RemoteAgentResult{}, err
	}
	res.Payments = pay.Payments()
	var unpaid *a2aHTTPError
	if res.Raised && errors.As(d.last, &unpaid) && unpaid.status == http.StatusPaymentRequired && len(res.Payments) > 0 {
		reason := res.Payments[len(res.Payments)-1].Error
		if reason == "" {
			reason = "payment failed"
		}
		res.Error = "A2A payment failed: " + reason
	}
	return res, nil
}

// delegateToken is _secret_token_provider: the bound workspace secret, read as the run's user when the call runs.
func (s *Service) delegateToken(ctx context.Context, ws scope.Workspace, userID, name string) (string, error) {
	if s.d.Secrets == nil {
		return "", errors.New("the secret store is not wired")
	}
	var token string
	err := s.readWS(ctx, ws, func(sess db.Session) error {
		v, err := s.d.Secrets.Manager(sess, userID).Get(ctx, name)
		if errors.Is(err, ksecrets.ErrNotFound) {
			return nil
		}
		token = v
		return err
	})
	if err != nil {
		return "", err
	}
	if token == "" {
		return "", fmt.Errorf("secret '%s' not found in this workspace", name)
	}
	return token, nil
}

func raisedResult(msg string) api.RemoteAgentResult {
	return api.RemoteAgentResult{Error: msg, Raised: true}
}

func failedResult(msg string) api.RemoteAgentResult { return api.RemoteAgentResult{Error: msg} }

// remoteDelegate is one call of an A2A agent known by its address.
type remoteDelegate struct {
	name, address, token string
	poll                 a2aPolling
	card, rpc            *http.Client
	endpoint             a2aInterface
	legacy               bool
	// last is the last call's failure.
	last error
}

type a2aInterface struct{ url, binding, version, tenant string }

type a2aTask struct {
	id, state string
	artifacts []string
	status    []string
	hasStatus bool
}

// a2aRaisedError fails the tool (ToolExecutionError).
type a2aRaisedError struct{ msg string }

func (e *a2aRaisedError) Error() string { return e.msg }

// a2aRPCError is a JSON-RPC error the agent answered.
type a2aRPCError struct{ msg string }

func (e *a2aRPCError) Error() string { return e.msg }

type a2aHTTPError struct{ status int }

func (e *a2aHTTPError) Error() string { return fmt.Sprintf("HTTP Error %d", e.status) }

type a2aNetError struct {
	err     error
	timeout bool
}

func (e *a2aNetError) Error() string { return "Network communication error: " + e.err.Error() }

func (d *remoteDelegate) delegate(ctx context.Context, message string) api.RemoteAgentResult {
	if err := d.resolve(ctx); err != nil {
		return raisedResult(err.Error())
	}
	answer, err := d.send(ctx, message)
	if err != nil {
		return d.failure(err)
	}
	if answer.message != nil {
		return d.success(strings.Join(answer.message, "\n"))
	}
	t := answer.task
	if !a2aTerminal(t.state) && !a2aInterrupted(t.state) {
		if t, err = d.pollTask(ctx, t); err != nil {
			return d.failure(err)
		}
	}
	switch {
	case t.state == "TASK_STATE_COMPLETED":
		return d.success(t.result())
	case a2aTerminal(t.state):
		return failedResult(fmt.Sprintf("'%s' ended the task as %s: %s", d.name, t.state, t.result()))
	case a2aInterrupted(t.state):
		return failedResult(fmt.Sprintf("'%s' stopped at %s on task %s: %s", d.name, t.state, t.id, t.result()))
	}
	return failedResult(fmt.Sprintf("'%s' is still working on task %s; no result within the delegation time limit", d.name, t.id))
}

func (d *remoteDelegate) success(text string) api.RemoteAgentResult {
	if text == "" {
		text = a2aNoOutput
	}
	return api.RemoteAgentResult{Success: true, Result: text}
}

func (d *remoteDelegate) failure(err error) api.RemoteAgentResult {
	d.last = err
	var rpc *a2aRPCError
	var status *a2aHTTPError
	var network *a2aNetError
	switch {
	case errors.As(err, &rpc):
		return failedResult(rpc.msg)
	case errors.As(err, &status):
		return raisedResult(fmt.Sprintf("A2A request failed with HTTP %d", status.status))
	case errors.As(err, &network) && network.timeout:
		return raisedResult(fmt.Sprintf("A2A call to '%s' timed out", d.name))
	}
	return raisedResult(err.Error())
}

func (t a2aTask) result() string {
	texts := t.artifacts
	if len(texts) == 0 && t.hasStatus {
		texts = t.status
	}
	if len(texts) == 0 {
		return a2aNoOutput
	}
	return strings.Join(texts, "\n")
}

func a2aTerminal(state string) bool {
	return slices.Contains([]string{"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}, state)
}

func a2aInterrupted(state string) bool {
	return state == "TASK_STATE_INPUT_REQUIRED" || state == "TASK_STATE_AUTH_REQUIRED"
}

func (d *remoteDelegate) pollTask(ctx context.Context, t a2aTask) (a2aTask, error) {
	for elapsed := time.Duration(0); elapsed < d.poll.budget; elapsed += d.poll.every {
		timer := time.NewTimer(d.poll.every)
		select {
		case <-ctx.Done():
			timer.Stop()
			return t, ctx.Err()
		case <-timer.C:
		}
		next, err := d.getTask(ctx, t.id)
		var raised *a2aRaisedError
		switch {
		case errors.As(err, &raised):
			return t, err
		case err != nil:
			if ctx.Err() != nil {
				return t, ctx.Err()
			}
			continue
		}
		t = next
		if a2aTerminal(t.state) || a2aInterrupted(t.state) {
			return t, nil
		}
	}
	return t, nil
}

// resolve reads the agent's card and picks the JSON-RPC endpoint to call: it must be on the
// address's own origin, which the credential is bound to.
func (d *remoteDelegate) resolve(ctx context.Context) error {
	target := strings.TrimRight(d.address, "/") + a2aCardPath
	fail := func(format string, a ...any) error {
		return &a2aRaisedError{msg: fmt.Sprintf("Could not read the agent card of '%s': ", d.name) + fmt.Sprintf(format, a...)}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return fail("Network communication error fetching agent card from %s: %v", target, err)
	}
	d.headers(req, a2aVersion10)
	resp, err := d.card.Do(req)
	if err != nil {
		return fail("Network communication error fetching agent card from %s: %v", target, urlCause(err))
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, a2aMaxAnswer))
	_ = resp.Body.Close()
	switch {
	case err != nil:
		return fail("Network communication error fetching agent card from %s: %v", target, err)
	case resp.StatusCode < 200 || resp.StatusCode >= 300:
		return fail("Failed to fetch agent card from %s (HTTP %d)", target, resp.StatusCode)
	}
	doc, err := a2aDecode(raw)
	if err != nil {
		return fail("Failed to parse JSON for agent card from %s: %v", target, err)
	}
	interfaces, err := a2aInterfaces(doc)
	if err != nil {
		return fail("Failed to validate agent card structure from %s: %v", target, err)
	}
	origin := a2aOrigin(d.address)
	var foreign []string
	for _, i := range interfaces {
		if a2aOrigin(i.url) != origin {
			foreign = append(foreign, i.url)
		}
	}
	if len(foreign) > 0 || len(interfaces) == 0 {
		named := strings.Join(foreign, ", ")
		if named == "" {
			named = "none"
		}
		return &a2aRaisedError{msg: fmt.Sprintf("The card of '%s' names no endpoint on %s: %s", d.name, origin, named)}
	}
	var jsonrpc []a2aInterface
	for _, i := range interfaces {
		if i.binding == a2aJSONRPC {
			jsonrpc = append(jsonrpc, i)
		}
	}
	best, ok := a2aBestInterface(jsonrpc)
	if !ok {
		return &a2aRaisedError{msg: "no compatible transports found."}
	}
	d.endpoint, d.legacy = best, a2aLegacy(best.version)
	return nil
}

// a2aInterfaces is parse_agent_card's supportedInterfaces, a legacy card's url,
// preferredTransport and additionalInterfaces mapped onto them.
func a2aInterfaces(doc any) ([]a2aInterface, error) {
	card, ok := doc.(map[string]any)
	if !ok {
		return nil, errors.New("an agent card is a JSON object")
	}
	list, has := card["supportedInterfaces"]
	if !has {
		main, _ := card["url"].(string)
		if main == "" {
			return nil, nil
		}
		version := "0.3.0"
		if v, ok := card["protocolVersion"].(string); ok {
			version = v
		}
		binding := a2aJSONRPC
		if v, ok := card["preferredTransport"].(string); ok {
			binding = v
		}
		mapped := []any{map[string]any{"url": main, "protocolBinding": binding, "protocolVersion": version}}
		extra, _ := card["additionalInterfaces"].([]any)
		for _, e := range extra {
			m, _ := e.(map[string]any)
			mapped = append(mapped, map[string]any{"url": m["url"], "protocolBinding": m["transport"], "protocolVersion": version})
		}
		list = mapped
	}
	items, ok := list.([]any)
	if !ok && list != nil {
		return nil, errors.New("supportedInterfaces is not a list")
	}
	var out []a2aInterface
	for _, it := range items {
		m, ok := it.(map[string]any)
		if !ok {
			return nil, errors.New("an interface is not an object")
		}
		var i a2aInterface
		for key, dst := range map[string]*string{"url": &i.url, "protocolBinding": &i.binding, "protocolVersion": &i.version, "tenant": &i.tenant} {
			switch v := m[key].(type) {
			case nil:
			case string:
				*dst = v
			default:
				return nil, fmt.Errorf("interface %s is not a string", key)
			}
		}
		out = append(out, i)
	}
	return out, nil
}

// a2aBestInterface is _find_best_interface: version 1.0, else the first newer, else the
// first at least 0.3, else the first without a version.
func a2aBestInterface(candidates []a2aInterface) (a2aInterface, bool) {
	for _, i := range candidates {
		if i.version == a2aVersion10 {
			return i, true
		}
	}
	var newer, legacy, unversioned *a2aInterface
	for k := range candidates {
		i := &candidates[k]
		if i.version == "" {
			if unversioned == nil {
				unversioned = i
			}
			continue
		}
		v, ok := parseVersion(i.version)
		if !ok {
			continue
		}
		if newer == nil && compareVersions(v, []int{1, 0}) > 0 {
			newer = i
		}
		if legacy == nil && compareVersions(v, []int{0, 3}) >= 0 {
			legacy = i
		}
	}
	for _, i := range []*a2aInterface{newer, legacy, unversioned} {
		if i != nil {
			return *i, true
		}
	}
	return a2aInterface{}, false
}

// a2aLegacy is is_legacy_version: 0.3 <= version < 1.0.
func a2aLegacy(version string) bool {
	v, ok := parseVersion(version)
	return ok && compareVersions(v, []int{0, 3}) >= 0 && compareVersions(v, []int{1, 0}) < 0
}

func parseVersion(s string) ([]int, bool) {
	s = strings.TrimPrefix(strings.ToLower(strings.TrimSpace(s)), "v")
	var out []int
	for p := range strings.SplitSeq(s, ".") {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return nil, false
		}
		out = append(out, n)
	}
	return out, len(out) > 0
}

func compareVersions(a, b []int) int {
	for i := range max(len(a), len(b)) {
		var x, y int
		if i < len(a) {
			x = a[i]
		}
		if i < len(b) {
			y = b[i]
		}
		if x != y {
			return x - y
		}
	}
	return 0
}

// a2aOrigin is _origin: scheme://netloc, lowercased.
func a2aOrigin(raw string) string {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return strings.ToLower(raw)
	}
	netloc := u.Host
	if u.User != nil {
		netloc = u.User.String() + "@" + netloc
	}
	return strings.ToLower(u.Scheme + "://" + netloc)
}

func (d *remoteDelegate) headers(req *http.Request, version string) {
	req.Header.Set(a2aVersionField, version)
	if d.token != "" {
		req.Header.Set("Authorization", "Bearer "+d.token)
	}
}

type a2aAnswer struct {
	task    a2aTask
	message []string
}

// send is SendMessage (message/send to a 0.3 agent) without waiting for the task to end.
func (d *remoteDelegate) send(ctx context.Context, message string) (a2aAnswer, error) {
	id := strings.ReplaceAll(uuid.NewString(), "-", "")
	method := "SendMessage"
	params := map[string]any{
		"message":       map[string]any{"messageId": id, "role": "ROLE_USER", "parts": []any{map[string]any{"text": message}}},
		"configuration": map[string]any{"returnImmediately": true},
	}
	if d.legacy {
		method = "message/send"
		params = map[string]any{
			"message":       map[string]any{"kind": "message", "messageId": id, "role": "user", "parts": []any{map[string]any{"kind": "text", "text": message}}},
			"configuration": map[string]any{"blocking": false},
		}
	} else if d.endpoint.tenant != "" {
		params["tenant"] = d.endpoint.tenant
	}
	result, err := d.call(ctx, method, params)
	if err != nil {
		return a2aAnswer{}, err
	}
	obj, _ := result.(map[string]any)
	if d.legacy {
		kind, _ := obj["kind"].(string)
		if kind == "" {
			if _, ok := obj["messageId"]; ok {
				kind = "message"
			} else if _, ok := obj["id"]; ok {
				kind = "task"
			}
		}
		switch kind {
		case "task":
			t, err := d.task(obj)
			return a2aAnswer{task: t}, err
		case "message":
			m, _ := obj["parts"].([]any)
			return a2aAnswer{message: d.texts(m, false)}, nil
		}
		return a2aAnswer{}, &a2aRaisedError{msg: "Response has neither task nor message"}
	}
	if t, ok := obj["task"].(map[string]any); ok {
		task, err := d.task(t)
		return a2aAnswer{task: task}, err
	}
	if m, ok := obj["message"].(map[string]any); ok {
		parts, _ := m["parts"].([]any)
		return a2aAnswer{message: d.texts(parts, false)}, nil
	}
	return a2aAnswer{}, &a2aRaisedError{msg: "Response has neither task nor message"}
}

func (d *remoteDelegate) getTask(ctx context.Context, id string) (a2aTask, error) {
	method := "GetTask"
	if d.legacy {
		method = "tasks/get"
	}
	result, err := d.call(ctx, method, map[string]any{"id": id})
	if err != nil {
		return a2aTask{}, err
	}
	obj, ok := result.(map[string]any)
	if !ok {
		return a2aTask{}, &a2aRaisedError{msg: "Failed to parse the task the agent answered"}
	}
	return d.task(obj)
}

// legacyStates maps a 0.3 task state onto 1.0's.
func legacyStates() map[string]string {
	return map[string]string{
		"submitted": "TASK_STATE_SUBMITTED", "working": "TASK_STATE_WORKING", "input-required": "TASK_STATE_INPUT_REQUIRED",
		"completed": "TASK_STATE_COMPLETED", "canceled": "TASK_STATE_CANCELED", "failed": "TASK_STATE_FAILED",
		"rejected": "TASK_STATE_REJECTED", "auth-required": "TASK_STATE_AUTH_REQUIRED", "unknown": "TASK_STATE_UNSPECIFIED",
	}
}

func (d *remoteDelegate) task(obj map[string]any) (a2aTask, error) {
	t := a2aTask{state: "TASK_STATE_UNSPECIFIED"}
	t.id, _ = obj["id"].(string)
	status, _ := obj["status"].(map[string]any)
	if state, ok := status["state"].(string); ok {
		if d.legacy {
			t.state = legacyStates()[state]
		} else {
			t.state = state
		}
		if t.state == "" || !strings.HasPrefix(t.state, "TASK_STATE_") {
			return t, &a2aRaisedError{msg: fmt.Sprintf("Invalid enum value %s for enum type a2a.v1.TaskState", state)}
		}
	}
	if m, ok := status["message"].(map[string]any); ok {
		parts, _ := m["parts"].([]any)
		t.hasStatus, t.status = true, d.texts(parts, true)
	}
	artifacts, _ := obj["artifacts"].([]any)
	for _, a := range artifacts {
		m, _ := a.(map[string]any)
		parts, _ := m["parts"].([]any)
		t.artifacts = append(t.artifacts, d.texts(parts, false)...)
	}
	return t, nil
}

// texts is _extract_parts_text: text parts, and data parts as JSON; textOnly keeps text parts only.
func (d *remoteDelegate) texts(parts []any, textOnly bool) []string {
	var out []string
	for _, p := range parts {
		m, _ := p.(map[string]any)
		kind, _ := m["kind"].(string)
		text, isText := m["text"].(string)
		data, isData := m["data"]
		switch {
		case isText && (!d.legacy || kind == "text"):
			out = append(out, text)
		case !textOnly && isData && (!d.legacy || kind == "data"):
			out = append(out, pyJSONDumps(data))
		}
	}
	return out
}

// call is one JSON-RPC request to the endpoint; its result, or the error the agent answered.
func (d *remoteDelegate) call(ctx context.Context, method string, params map[string]any) (any, error) {
	body, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "method": method, "params": params, "id": uuid.NewString()})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, d.endpoint.url, bytes.NewReader(body))
	if err != nil {
		return nil, &a2aNetError{err: err}
	}
	req.Header.Set("Content-Type", "application/json")
	version := a2aVersion10
	if d.legacy {
		version = a2aVersion03
	}
	d.headers(req, version)
	resp, err := d.rpc.Do(req)
	if err != nil {
		var ue *url.Error
		return nil, &a2aNetError{err: urlCause(err), timeout: errors.As(err, &ue) && ue.Timeout()}
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, a2aMaxAnswer))
	_ = resp.Body.Close()
	switch {
	case err != nil:
		return nil, &a2aNetError{err: err}
	case resp.StatusCode < 200 || resp.StatusCode >= 300:
		return nil, &a2aHTTPError{status: resp.StatusCode}
	}
	doc, err := a2aDecode(raw)
	if err != nil {
		return nil, &a2aNetError{err: fmt.Errorf("JSON Decode Error: %w", err)}
	}
	answer, ok := doc.(map[string]any)
	if !ok {
		return nil, &a2aRaisedError{msg: "the agent's answer is not a JSON-RPC response"}
	}
	if e, ok := answer["error"].(map[string]any); ok && len(e) > 0 {
		return nil, d.rpcError(e)
	}
	return answer["result"], nil
}

// rpcError is _create_jsonrpc_error: an A2A error's message, or the code and message of one
// the SDK has no type for.
func (d *remoteDelegate) rpcError(e map[string]any) error {
	msg, ok := e["message"].(string)
	if !ok {
		msg = "Unknown Error"
		if !d.legacy {
			msg = fmt.Sprint(e)
		}
	}
	code, isInt := jsonInt(e["code"])
	known := isInt && (code == -32700 || (code >= -32603 && code <= -32600) || (code >= -32009 && code <= -32001))
	if known || d.legacy {
		return &a2aRPCError{msg: msg}
	}
	return &a2aRPCError{msg: fmt.Sprintf("JSON-RPC Error %v: %s", pyRepr(e["code"]), msg)}
}

func jsonInt(v any) (int64, bool) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := n.Int64()
	return i, err == nil
}

func urlCause(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		return ue.Err
	}
	return err
}

func a2aDecode(raw []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if dec.More() {
		return nil, errors.New("extra data after the JSON value")
	}
	return v, nil
}

// pyJSONDumps is json.dumps(MessageToDict(value)): a protobuf Value, so every number a float.
func pyJSONDumps(v any) string {
	var b strings.Builder
	pyDumpValue(&b, v)
	return b.String()
}

func pyDumpValue(b *strings.Builder, v any) {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		b.WriteString(strconv.FormatBool(x))
	case string:
		pyQuoteASCII(b, x)
	case json.Number:
		f, err := x.Float64()
		if err != nil {
			b.WriteString(x.String())
			return
		}
		b.WriteString(pyFloat(f))
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		slices.Sort(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteString(", ")
			}
			pyQuoteASCII(b, k)
			b.WriteString(": ")
			pyDumpValue(b, x[k])
		}
		b.WriteByte('}')
	case []any:
		b.WriteByte('[')
		for i, it := range x {
			if i > 0 {
				b.WriteString(", ")
			}
			pyDumpValue(b, it)
		}
		b.WriteByte(']')
	}
}

func pyFloat(f float64) string {
	sci := strconv.FormatFloat(f, 'e', -1, 64)
	exp, _ := strconv.Atoi(sci[strings.IndexByte(sci, 'e')+1:])
	if exp < -4 || exp >= 16 {
		return sci
	}
	fixed := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(fixed, ".") {
		fixed += ".0"
	}
	return fixed
}

func pyQuoteASCII(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			switch {
			case r < 0x20 || (r >= 0x7f && r < 0x10000):
				fmt.Fprintf(b, `\u%04x`, r)
			case r >= 0x10000:
				r -= 0x10000
				fmt.Fprintf(b, `\u%04x\u%04x`, 0xd800+(r>>10), 0xdc00+(r&0x3ff))
			default:
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}
