package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"sort"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

// mediaTimeout is _IMAGE_TIMEOUT_SECONDS: a decision or a media call waits this long.
const mediaTimeout = 300 * time.Second

var _ api.Decider = (*Service)(nil)

func callFailed(what string, status int) error {
	if status == 0 {
		return &api.ModelCallError{Msg: what + " failed: no answer"}
	}
	return &api.ModelCallError{Msg: fmt.Sprintf("%s failed: HTTP %d", what, status)}
}

// validateQuestions is _validate_questions.
func validateQuestions(questions map[string]any) error {
	if len(questions) == 0 {
		return &api.ModelCallError{Msg: "a decision needs at least one question"}
	}
	keys := make([]string, 0, len(questions))
	for k := range questions {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, key := range keys {
		q, ok := questions[key].(map[string]any)
		if !ok {
			return &api.ModelCallError{Msg: fmt.Sprintf("question '%s' must be an object", key)}
		}
		kind, _ := q["type"].(string)
		if kind != api.QuestionChoice && kind != api.QuestionScore {
			return &api.ModelCallError{Msg: fmt.Sprintf("question '%s' has type %v; expected one of choice, score", key, q["type"])}
		}
		if s, _ := q["instructions"].(string); s == "" {
			return &api.ModelCallError{Msg: fmt.Sprintf("question '%s' needs instructions", key)}
		}
		switch c := q["criteria"].(type) {
		case map[string]any:
			if kind == api.QuestionChoice && len(c) > 0 {
				continue
			}
		case []any:
			if kind == api.QuestionScore && len(c) > 0 {
				continue
			}
		}
		if kind == api.QuestionChoice {
			return &api.ModelCallError{Msg: fmt.Sprintf("choice question '%s' needs criteria naming each option", key)}
		}
		return &api.ModelCallError{Msg: fmt.Sprintf("score question '%s' needs a non-empty criteria list", key)}
	}
	return nil
}

// Decide is DecisionModel.evaluate over a resolved model.
func (s *Service) Decide(ctx context.Context, p api.Principal, d api.Decision) (api.DecisionReply, error) {
	if err := validateQuestions(d.Questions); err != nil {
		return api.DecisionReply{}, err
	}
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return api.DecisionReply{}, err
	}
	m := d.Model
	profile, err := profileOf(m.Provider)
	if err != nil {
		return api.DecisionReply{}, err
	}
	url := profile.APIURL(s.localEndpoint(m.EndpointURL), "/systemone")
	if url == "" {
		return api.DecisionReply{}, &api.ModelCallError{Msg: fmt.Sprintf("model instance %s uses provider '%s', which has no public address, and has no endpoint_url configured", m.ModelID, m.ProviderType)}
	}
	key, err := s.apiKey(ctx, ws, p.UserID, m.APIKeySecret, m.ManagedBy, d.Funded)
	if err != nil {
		return api.DecisionReply{}, err
	}
	var body bytes.Buffer
	enc := json.NewEncoder(&body)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(map[string]any{"model": m.ModelName, "state": d.State, "questions": d.Questions}); err != nil {
		return api.DecisionReply{}, err
	}
	cctx, cancel := context.WithTimeout(ctx, mediaTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(cctx, http.MethodPost, url, &body)
	if err != nil {
		return api.DecisionReply{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range profile.Headers(key) {
		req.Header.Set(k, v)
	}
	resp, err := (&http.Client{Transport: s.roundTripper(m.ManagedBy), CheckRedirect: transport.NoRedirects}).Do(req)
	if err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			slog.WarnContext(ctx, "Decision model endpoint refused by the outbound policy", "error", err.Error())
			return api.DecisionReply{}, &api.ModelCallError{Msg: "decision model endpoint points to an address this deployment does not call"}
		}
		slog.WarnContext(ctx, "Decision call got no answer", "error", err.Error())
		return api.DecisionReply{}, callFailed("decision", 0)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return api.DecisionReply{}, callFailed("decision", 0)
	}
	if resp.StatusCode/100 != 2 {
		slog.WarnContext(ctx, "decision endpoint answered an error", "status", resp.StatusCode, "body", truncate(string(raw), 500))
		return api.DecisionReply{}, callFailed("decision", resp.StatusCode)
	}
	return decisionReply(m, d.Questions, raw)
}

func decisionReply(m api.ResolvedModel, questions map[string]any, raw []byte) (api.DecisionReply, error) {
	var payload map[string]any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&payload); err != nil {
		return api.DecisionReply{}, &api.ModelCallError{Msg: "decision returned a body that is not a JSON object"}
	}
	rawAnswers, ok := payload["answers"].(map[string]any)
	if !ok {
		return api.DecisionReply{}, &api.ModelCallError{Msg: "decision returned no answers"}
	}
	out := api.DecisionReply{Answers: map[string]map[string]any{}}
	for key, q := range questions {
		expected, _ := q.(map[string]any)["type"].(string)
		answer, ok := rawAnswers[key].(map[string]any)
		if !ok || answer["type"] != expected {
			return api.DecisionReply{}, &api.ModelCallError{Msg: fmt.Sprintf("decision returned no %s answer for question '%s'", expected, key)}
		}
		if answer[expected] == nil {
			return api.DecisionReply{}, &api.ModelCallError{Msg: fmt.Sprintf("decision answer for '%s' has no %s value", key, expected)}
		}
		out.Answers[key] = answer
	}
	usage := map[string]any{}
	if u, present := payload["usage"]; present && u != nil {
		if usage, ok = u.(map[string]any); !ok {
			return api.DecisionReply{}, &api.ModelCallError{Msg: "response usage is not an object"}
		}
	}
	in, inOK := intOf(usage["input_tokens"])
	outTokens, outOK := intOf(usage["output_tokens"])
	if !inOK || !outOK {
		return api.DecisionReply{}, &api.ModelCallError{Msg: "decision response has no input_tokens/output_tokens usage"}
	}
	out.InputTokens, out.OutputTokens = in, outTokens
	if c, present := usage["cost"]; present && c != nil {
		d, err := money.Parse(fmt.Sprint(c))
		if err != nil {
			return api.DecisionReply{}, &api.ModelCallError{Msg: "decision response reported a cost that is not a number"}
		}
		out.CostUSD = &d
		return out, nil
	}
	if m.Prices.Input == nil || m.Prices.Output == nil {
		slog.Error("Decision model instance reported no cost and its spec has no per-token prices; the call's cost is unknown",
			"model_id", m.ModelID, "model_name", m.ModelName)
		return out, nil
	}
	cost := money.FromInt(in).Mul(*m.Prices.Input).Add(money.FromInt(outTokens).Mul(*m.Prices.Output))
	out.CostUSD = &cost
	return out, nil
}

func intOf(v any) (int64, bool) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := n.Int64()
	return i, err == nil
}

func truncate(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
