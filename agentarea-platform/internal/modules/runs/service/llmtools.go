package service

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"path"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	sandboxapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

// llmToolset calls the models the agent's settings list: one chat call
// without tools, or one decision, funded and charged as media's calls are.
const llmToolset = "agentarea/llm"

type llmTools struct {
	s      *Service
	policy api.Policy
}

func (s *Service) llmCaller(in ToolCall) ToolCaller {
	b := in.Binding
	if b.Source != "code" || b.Code == nil || b.Code.Namespace != llmToolset {
		return nil
	}
	return llmTools{s: s, policy: in.Policy}
}

func (t llmTools) Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	d := t.s.d
	if d.ModelNames == nil || d.Resolver == nil || d.Models == nil || d.Describer == nil || d.Decider == nil || d.Runtime == nil {
		return ToolOutput{}, errors.New("agentarea/llm is not wired")
	}
	if inv.TaskID == "" {
		return mediaError("agentarea/llm reads and writes a task's workspace; this call has no task"), nil
	}
	var out ToolOutput
	var err error
	switch inv.Binding.Code.Method {
	case "call":
		out, err = t.call(ctx, inv)
	case "decide":
		out, err = t.decide(ctx, inv)
	default:
		return unknownTool(inv.ToolName), nil
	}
	if err != nil {
		return llmFailure(err)
	}
	return out, nil
}

// llmFailure is mediaFailure, and a reasoning setting the provider refuses or
// an escalation the gate asks for, answered as the tool's error.
func llmFailure(err error) (ToolOutput, error) {
	var app *durable.ApplicationError
	if errors.As(err, &app) && (app.Type == "ReasoningSettingError" || app.Type == "EscalationRequiredError") {
		return mediaError(app.Message), nil
	}
	return mediaFailure(err)
}

func llmString(args map[string]any, name string, required bool) (string, error) {
	v, present := args[name]
	if !present || v == nil {
		if required {
			return "", errors.New(name + " is required")
		}
		return "", nil
	}
	s, ok := v.(string)
	if !ok {
		return "", errors.New(name + " must be a string")
	}
	return s, nil
}

func llmTokensArg(args map[string]any, name string) (*int, error) {
	v, present := args[name]
	if !present || v == nil {
		return nil, nil
	}
	n, ok := v.(float64)
	if !ok || n != math.Trunc(n) || n <= 0 || n > math.MaxInt32 {
		return nil, errors.New(name + " must be a positive integer")
	}
	i := int(n)
	return &i, nil
}

func llmObject(args map[string]any, name string, required bool) (map[string]any, error) {
	v, present := args[name]
	if !present || v == nil {
		if required {
			return nil, errors.New(name + " is required")
		}
		return nil, nil
	}
	o, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New(name + " must be an object")
	}
	return o, nil
}

// llmModel is a model the agent may call, by the names a call may give it.
type llmModel struct {
	entry api.ToolModel
	name  modelsapi.InstanceName
}

func (m llmModel) describe() string {
	return fmt.Sprintf("'%s' (%s, %s)", m.name.Name, m.name.ModelName, m.name.Kind)
}

// pickLLMModel is the model ref names among allowed: by id, else by its
// instance's name, else by its model's name; problem when none or several.
func pickLLMModel(allowed []llmModel, ref string) (llmModel, string) {
	var matches []llmModel
	if u, err := uuid.Parse(ref); err == nil {
		for _, m := range allowed {
			if strings.EqualFold(m.name.ID, u.String()) {
				matches = append(matches, m)
			}
		}
	} else {
		for _, byModel := range []bool{false, true} {
			for _, m := range allowed {
				if (!byModel && m.name.Name == ref) || (byModel && m.name.ModelName == ref) {
					matches = append(matches, m)
				}
			}
			if len(matches) > 0 {
				break
			}
		}
	}
	names := make([]string, len(allowed))
	for i, m := range allowed {
		names[i] = m.describe()
	}
	switch {
	case len(matches) == 1:
		return matches[0], ""
	case len(matches) > 1:
		found := make([]string, len(matches))
		for i, m := range matches {
			found[i] = m.describe()
		}
		return llmModel{}, fmt.Sprintf("model '%s' names %d of the models this agent may call: %s; give its id or a name only one of them has",
			ref, len(matches), strings.Join(found, ", "))
	case len(allowed) == 0:
		return llmModel{}, fmt.Sprintf("model '%s' is not one this agent may call; none of the models its agentarea/llm settings list exists any more", ref)
	}
	return llmModel{}, fmt.Sprintf("model '%s' is not one this agent may call; it may call %s", ref, strings.Join(names, ", "))
}

// model is the allowed model the call names, of kind; problem when it names another.
func (t llmTools) model(ctx context.Context, inv ToolInvocation, kind string) (llmModel, string, error) {
	ref, err := llmString(inv.Args, "model", true)
	if err != nil {
		return llmModel{}, err.Error(), nil
	}
	ws, err := workspace(inv.Principal)
	if err != nil {
		return llmModel{}, "", err
	}
	var allowed []llmModel
	for _, e := range inv.Binding.Code.Models {
		name, found, err := t.s.d.ModelNames.InstanceName(ctx, ws, e.ModelID)
		if err != nil {
			return llmModel{}, "", err
		}
		if found {
			allowed = append(allowed, llmModel{entry: e, name: name})
		}
	}
	m, problem := pickLLMModel(allowed, ref)
	if problem != "" {
		return llmModel{}, problem, nil
	}
	if m.name.Kind != kind {
		if kind == modelsapi.KindChat {
			return llmModel{}, fmt.Sprintf("model '%s' is a %s model; ask it with llm_decide", ref, m.name.Kind), nil
		}
		return llmModel{}, fmt.Sprintf("model '%s' is a %s model; call it with llm_call", ref, m.name.Kind), nil
	}
	return m, "", nil
}

// outputPath is the call's output, "" when it returns its answer; problem when the path is refused.
func outputPath(args map[string]any) (string, string) {
	p, err := llmString(args, "output", false)
	if err != nil {
		return "", err.Error()
	}
	if p == "" {
		return "", ""
	}
	if refusal := domain.FilePathRefusal(p); refusal != "" {
		return "", refusal
	}
	if domain.BinaryFileRefusal(p) != "" {
		return "", fmt.Sprintf("output %s names a binary file; the answer is text: give a .txt, .md or .json path", p)
	}
	return p, ""
}

// reasoning is what the call reasons with: a level or a budget the call
// gives, else the entry's; problem when they conflict or the model takes no such level.
func reasoning(args map[string]any, entry api.ToolModel, model modelsapi.ResolvedModel) (string, *int, string) {
	effort, err := llmString(args, "reasoning_effort", false)
	if err != nil {
		return "", nil, err.Error()
	}
	budget, err := llmTokensArg(args, "reasoning_max_tokens")
	if err != nil {
		return "", nil, err.Error()
	}
	switch {
	case effort != "" && budget != nil:
		return "", nil, "set reasoning_effort or reasoning_max_tokens, not both"
	case effort == "" && budget == nil:
		effort, budget = entry.ReasoningEffort, entry.ReasoningMaxTokens
	}
	if effort == "" {
		return "", budget, ""
	}
	levels := model.ReasoningLevels
	if len(levels) == 0 {
		levels = model.Provider.ReasoningLevels
	}
	if len(levels) == 0 {
		return "", nil, fmt.Sprintf("model %s takes no reasoning_effort", model.ModelName)
	}
	if !slices.Contains(levels, effort) {
		return "", nil, fmt.Sprintf("model %s takes reasoning_effort %s, not %s", model.ModelName, strings.Join(levels, ", "), effort)
	}
	return effort, nil, ""
}

// jsonAnswer is the answer without a code fence around it; problem when it is not JSON.
func jsonAnswer(answer string) (string, string) {
	if rest, ok := strings.CutPrefix(answer, "```"); ok && strings.HasSuffix(rest, "```") {
		rest = strings.TrimSuffix(rest, "```")
		if nl := strings.IndexByte(rest, '\n'); nl >= 0 && !strings.ContainsAny(rest[:nl], "{[\"") {
			rest = rest[nl+1:]
		}
		answer = strings.TrimSpace(rest)
	}
	if !json.Valid([]byte(answer)) {
		return "", "the model answered text that is not JSON"
	}
	return answer, ""
}

// attachments are files as the parts a model reads, by read_file's rules:
// an image or a PDF of at most pdfPagesWithoutRange pages, within what one
// model call takes; problem when one is refused.
func (t llmTools) attachments(ctx context.Context, inv ToolInvocation, model modelsapi.ResolvedModel) ([]domain.ContentPart, string, error) {
	v, present := inv.Args["files"]
	if !present || v == nil {
		return nil, "", nil
	}
	list, ok := v.([]any)
	if !ok {
		return nil, "files must be a list of task workspace paths", nil
	}
	paths := make([]string, len(list))
	for i, x := range list {
		if paths[i], ok = x.(string); !ok {
			return nil, "files must be a list of task workspace paths", nil
		}
	}
	if len(paths) == 0 {
		return nil, "", nil
	}
	if !model.SupportsVision {
		return nil, fmt.Sprintf("model %s does not read images or PDFs", model.ModelName), nil
	}
	fits := domain.ImageLimits{MaxBytes: model.Provider.MaxImageBytes, MaxEdge: model.Provider.MaxImageEdge, PDF: model.Provider.PDFInput}
	var parts []domain.ContentPart
	images, pages := 0, 0
	for _, name := range paths {
		if refusal := domain.FilePathRefusal(name); refusal != "" {
			return nil, refusal, nil
		}
		data, _, err := t.s.d.Runtime.ReadFile(ctx, inv.Principal.WorkspaceID, filesTask(inv), name)
		if errors.Is(err, sandboxapi.ErrFileNotFound) {
			return nil, "file " + name + " does not exist", nil
		}
		if err != nil {
			return nil, "", err
		}
		ref := domain.ImageRef{Size: int64(len(data))}
		if http.DetectContentType(data) == pdfMimeType {
			n, err := pdfPageCount(ctx, data)
			if err != nil {
				return nil, name + ": " + err.Error(), nil
			}
			if n > pdfPagesWithoutRange {
				return nil, fmt.Sprintf("%s has %d pages; a PDF attached here has at most %d: cut the pages you need into a new PDF in the shell",
					name, n, pdfPagesWithoutRange), nil
			}
			ref.MimeType, ref.Pages = pdfMimeType, n
			pages += n
		} else {
			info, isImage, err := inspectImage(data)
			if !isImage {
				return nil, name + " is neither an image (PNG, JPEG, GIF, WebP) nor a PDF", nil
			}
			if err != nil {
				return nil, name + ": " + err.Error(), nil
			}
			ref.MimeType, ref.Width, ref.Height = info.MimeType, info.Width, info.Height
			images++
		}
		if refusal := fits.Refusal(ref); refusal != "" {
			return nil, name + ": " + refusal, nil
		}
		url := "data:" + ref.MimeType + ";base64," + base64.StdEncoding.EncodeToString(data)
		if ref.MimeType == pdfMimeType {
			parts = append(parts, domain.ContentPart{Type: "file", FileData: url, Filename: path.Base(name)})
		} else {
			parts = append(parts, domain.ContentPart{Type: "image_url", ImageURL: url})
		}
	}
	switch {
	case images > domain.MaxImagesPerModelCall:
		return nil, fmt.Sprintf("files has %d images; one call takes at most %d", images, domain.MaxImagesPerModelCall), nil
	case pages > domain.MaxPDFPagesPerModelCall:
		return nil, fmt.Sprintf("files has %d PDF pages; one call takes at most %d", pages, domain.MaxPDFPagesPerModelCall), nil
	}
	return parts, "", nil
}

func (t llmTools) call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	s, p := t.s, inv.Principal
	m, problem, err := t.model(ctx, inv, modelsapi.KindChat)
	if err != nil || problem != "" {
		return mediaError(problem), err
	}
	prompt, err := llmString(inv.Args, "prompt", true)
	if err != nil {
		return mediaError(err.Error()), nil
	}
	system, err := llmString(inv.Args, "system", false)
	if err != nil {
		return mediaError(err.Error()), nil
	}
	requested, err := llmTokensArg(inv.Args, "max_tokens")
	if err != nil {
		return mediaError(err.Error()), nil
	}
	if requested == nil {
		requested = m.entry.MaxTokens
	}
	output, problem := outputPath(inv.Args)
	if problem != "" {
		return mediaError(problem), nil
	}
	schemaArg, err := llmObject(inv.Args, "schema", false)
	if err != nil {
		return mediaError(err.Error()), nil
	}
	model, err := s.d.Resolver.Model(ctx, modelsapi.Principal(p), m.entry.ModelID)
	if err != nil {
		return ToolOutput{}, err
	}
	effort, budget, problem := reasoning(inv.Args, m.entry, model)
	if problem != "" {
		return mediaError(problem), nil
	}
	parts, problem, err := t.attachments(ctx, inv, model)
	if err != nil || problem != "" {
		return mediaError(problem), err
	}
	maxTokens, err := maxTokensFor(requested, model.MaxOutputTokens, t.policy)
	if err != nil {
		return ToolOutput{}, err
	}
	var messages []domain.ModelMessage
	if system != "" {
		messages = append(messages, domain.ModelMessage{Role: "system", Content: system})
	}
	user := domain.ModelMessage{Role: "user", Content: prompt}
	if len(parts) > 0 {
		user = domain.ModelMessage{Role: "user", Parts: append([]domain.ContentPart{{Type: "text", Text: prompt}}, parts...)}
	}
	messages = append(messages, user)
	if err := s.gateModelCall(ctx, p, model, t.policy); err != nil {
		return ToolOutput{}, err
	}
	if err := s.refuseAtSpendCap(ctx, p, t.policy.Budget, modelCall{TaskID: inv.TaskID, Model: model.ModelName, Tool: inv.ToolName}); err != nil {
		return ToolOutput{}, err
	}
	held := maxTokens
	if budget != nil {
		held += *budget
	}
	f, err := s.holdModelCall(ctx, p, model, estimateVendorCost(messages, held, model.Prices), "llm-tool:"+inv.CallRef+":"+strings.ReplaceAll(uuid.NewString(), "-", ""))
	if err != nil {
		return ToolOutput{}, err
	}
	reply, err := s.d.Models.Call(ctx, modelsapi.Principal(p), modelsapi.Call{
		Model: model, Messages: modelMessages(messages), MaxTokens: maxTokens, ReasoningEffort: effort, ReasoningMaxTokens: budget, ResponseSchema: schemaArg, Funded: f.platformFunded,
	})
	if err != nil {
		s.releaseHold(ctx, f, "the agentarea/llm call did not complete")
		return ToolOutput{}, err
	}
	charge, err := s.chargeModelCall(ctx, f, reply.ProviderCostUSD)
	if err != nil {
		return ToolOutput{}, err
	}
	out := ToolOutput{ModelCost: charge.Amount, ModelBilling: &charge, CostUnknown: charge.CostUnknown, Source: "builtin"}
	answer := strings.TrimSpace(reply.Content)
	if schemaArg != nil {
		var problem string
		if answer, problem = jsonAnswer(answer); problem != "" {
			out.Result, out.Error = "Error: "+problem, problem
			return out, nil
		}
	}
	return t.deliver(ctx, inv, out, output, answer)
}

func (t llmTools) decide(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	s, p := t.s, inv.Principal
	m, problem, err := t.model(ctx, inv, modelsapi.KindDecision)
	if err != nil || problem != "" {
		return mediaError(problem), err
	}
	state, err := llmObject(inv.Args, "state", true)
	if err != nil {
		return mediaError(err.Error()), nil
	}
	questions, err := llmObject(inv.Args, "questions", true)
	if err != nil {
		return mediaError(err.Error()), nil
	}
	output, problem := outputPath(inv.Args)
	if problem != "" {
		return mediaError(problem), nil
	}
	model, err := s.d.Describer.Describe(ctx, modelsapi.Principal(p), m.entry.ModelID, modelsapi.KindDecision)
	if err != nil {
		return ToolOutput{}, err
	}
	if err := s.gateModelCall(ctx, p, model, t.policy); err != nil {
		return ToolOutput{}, err
	}
	if err := s.refuseAtSpendCap(ctx, p, t.policy.Budget, modelCall{TaskID: inv.TaskID, Model: model.ModelName, Tool: inv.ToolName}); err != nil {
		return ToolOutput{}, err
	}
	maxOut := 0
	if model.MaxOutputTokens != nil {
		maxOut = *model.MaxOutputTokens
	}
	request := []domain.ModelMessage{{Role: "user", Content: decisionRequestText(api.DecideOnce{State: state, Questions: questions})}}
	f, err := s.holdModelCall(ctx, p, model, estimateVendorCost(request, maxOut, model.Prices), "llm-tool:"+inv.CallRef+":"+strings.ReplaceAll(uuid.NewString(), "-", ""))
	if err != nil {
		return ToolOutput{}, err
	}
	reply, err := s.d.Decider.Decide(ctx, modelsapi.Principal(p), modelsapi.Decision{Model: model, Funded: f.platformFunded, State: state, Questions: questions})
	if err != nil {
		s.releaseHold(ctx, f, "the agentarea/llm decision did not complete")
		return ToolOutput{}, err
	}
	var charge ChargeLine
	if reply.CostUSD == nil {
		charge = s.chargeUnknownCost(ctx, f)
	} else if charge, err = s.chargeModelCall(ctx, f, *reply.CostUSD); err != nil {
		return ToolOutput{}, err
	}
	out := ToolOutput{ModelCost: charge.Amount, ModelBilling: &charge, CostUnknown: charge.CostUnknown, Source: "builtin"}
	answers, err := json.Marshal(reply.Answers)
	if err != nil {
		return ToolOutput{}, err
	}
	return t.deliver(ctx, inv, out, output, string(answers))
}

// deliver is the answer as the tool's result, or written to output with its path and size in its place.
func (t llmTools) deliver(ctx context.Context, inv ToolInvocation, out ToolOutput, output, answer string) (ToolOutput, error) {
	if output == "" {
		out.Success, out.Result = true, answer
		return out, nil
	}
	if _, err := t.s.d.Runtime.PutFile(ctx, inv.Principal.WorkspaceID, filesTask(inv), output, []byte(answer)); err != nil {
		// The model was paid for the answer; the charge stands though the file is lost.
		t.s.d.Log.ErrorContext(ctx, "model answer could not be saved", "task_id", inv.TaskID, "error", err)
		out.Result, out.Error = "The answer was generated but could not be saved: "+err.Error(), err.Error()
		return out, nil
	}
	out.Success = true
	out.Result = orderedJSON{{"file_path", output}, {"size", len(answer)}}.String()
	return out, nil
}
