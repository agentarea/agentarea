package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// mediaToolset is media_toolset.py: images and videos generated with the
// workspace's image and video models (MediaGenerationService), saved to the
// task's sandbox so the shell sees them.
const (
	mediaToolset = "agentarea/media"
	mediaDir     = "media"
)

type mediaTools struct {
	s *Service
	// budget is the run's frozen budget the spend cap check merges with the caps set now.
	budget *api.BudgetPolicy
}

func (s *Service) mediaCaller(in ToolCall) ToolCaller {
	b := in.Binding
	if b.Source != "code" || b.Code == nil || b.Code.Namespace != mediaToolset {
		return nil
	}
	return mediaTools{s: s, budget: in.Policy.Budget}
}

func (t mediaTools) Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	d := t.s.d
	if d.Describer == nil || d.Media == nil || d.VideoJobs == nil || d.Runtime == nil {
		return ToolOutput{}, errors.New("agentarea/media is not wired")
	}
	if inv.TaskID == "" {
		return mediaError("agentarea/media saves into a task's workspace; this call has no task"), nil
	}
	var out ToolOutput
	var err error
	switch inv.Binding.Code.Method {
	case "generate_image":
		out, err = t.generateImage(ctx, inv)
	case "generate_video":
		out, err = t.generateVideo(ctx, inv)
	case "get_video":
		out, err = t.getVideo(ctx, inv)
	default:
		return unknownTool(inv.ToolName), nil
	}
	if err != nil {
		return mediaFailure(err)
	}
	return out, nil
}

func mediaError(msg string) ToolOutput {
	return ToolOutput{Result: "Error: " + msg, Error: msg, Source: "builtin"}
}

// mediaFailure answers a refusal or a failed model call as the tool's error; anything else is raised.
func mediaFailure(err error) (ToolOutput, error) {
	var app *durable.ApplicationError
	if errors.As(err, &app) {
		switch app.Type {
		case "SpendCapReachedError":
			return mediaError(app.Message), nil
		case "GovernanceDeniedError":
			return mediaError(strings.TrimPrefix(app.Message, "billing: ")), nil
		}
		return ToolOutput{}, err
	}
	var callErr *modelsapi.ModelCallError
	if errors.As(err, &callErr) {
		return mediaError(callErr.Msg), nil
	}
	if errors.Is(err, modelsapi.ErrNotFound) || errors.Is(err, modelsapi.ErrRefused) || errors.Is(err, modelsapi.ErrKindMismatch) {
		return mediaError(err.Error()), nil
	}
	return ToolOutput{}, err
}

func mediaHoldKey(callRef string) string {
	return "media:" + callRef + ":" + strings.ReplaceAll(uuid.NewString(), "-", "")
}

// mediaExtension is mimetypes.guess_extension for the types the models return.
func mediaExtension(mediaType string) string {
	switch mediaType {
	case "image/png":
		return ".png"
	case "image/jpeg":
		return ".jpg"
	case "image/gif":
		return ".gif"
	case "image/webp":
		return ".webp"
	case "video/mp4":
		return ".mp4"
	case "video/webm":
		return ".webm"
	case "video/quicktime":
		return ".mov"
	case "video/mpeg":
		return ".mpeg"
	}
	return ".bin"
}

func (t mediaTools) charge(ctx context.Context, f funding, vendorCost *money.Decimal) (ChargeLine, error) {
	if vendorCost == nil {
		return t.s.chargeUnknownCost(ctx, f), nil
	}
	return t.s.chargeModelCall(ctx, f, *vendorCost)
}

func optionalString(args map[string]any, name string) (string, error) {
	v, present := args[name]
	if !present || v == nil {
		return "", nil
	}
	s, ok := v.(string)
	if !ok {
		return "", fmt.Errorf("%s must be a string", name)
	}
	return s, nil
}

func (t mediaTools) generateImage(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	s := t.s
	prompt, err := stringArg(inv.Args, "prompt")
	if err != nil {
		return ToolOutput{}, err
	}
	size, err := optionalString(inv.Args, "size")
	if err != nil {
		return mediaError(err.Error()), nil
	}
	modelID := inv.Binding.Code.ImageModelID
	if modelID == "" {
		return mediaError("no image model is configured for agentarea/media"), nil
	}
	p := inv.Principal
	model, err := s.d.Describer.Describe(ctx, modelsapi.Principal(p), modelID, modelsapi.KindImage)
	if err != nil {
		return ToolOutput{}, err
	}
	if err := s.refuseAtSpendCap(ctx, p, t.budget); err != nil {
		return ToolOutput{}, err
	}
	f, err := s.holdModelCall(ctx, p, model, model.Prices.Image, mediaHoldKey(inv.CallRef))
	if err != nil {
		return ToolOutput{}, err
	}
	image, err := s.d.Media.GenerateImage(ctx, modelsapi.Principal(p), modelsapi.ImageCall{Model: model, Funded: f.platformFunded, Prompt: prompt, Size: size})
	if err != nil {
		s.releaseHold(ctx, f, "the image was not generated")
		return ToolOutput{}, err
	}
	charge, err := t.charge(ctx, f, image.CostUSD)
	if err != nil {
		return ToolOutput{}, err
	}
	out := ToolOutput{ModelCost: charge.Amount, ModelBilling: &charge, CostUnknown: charge.CostUnknown, Source: "builtin"}
	path := mediaDir + "/image-" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12] + mediaExtension(image.MediaType)
	if _, err := s.d.Runtime.PutFile(ctx, p.WorkspaceID, filesTask(inv), path, image.Content); err != nil {
		// The provider was paid for the image; the charge stands though the file is lost.
		s.d.Log.ErrorContext(ctx, "generated image could not be saved", "task_id", inv.TaskID, "error", err)
		out.Result, out.Error = "The image was generated but could not be saved: "+err.Error(), err.Error()
		return out, nil
	}
	out.Success, out.ArtifactPaths = true, []string{path}
	out.Result = orderedJSON{{"file_path", path}, {"media_type", image.MediaType}, {"size", len(image.Content)}}.String()
	return out, nil
}

func (t mediaTools) generateVideo(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	s := t.s
	prompt, err := stringArg(inv.Args, "prompt")
	if err != nil {
		return ToolOutput{}, err
	}
	var duration *int
	if v, present := inv.Args["duration"]; present && v != nil {
		n, ok := v.(float64)
		if !ok || n != float64(int(n)) || n <= 0 {
			return mediaError("duration must be a whole number of seconds"), nil
		}
		seconds := int(n)
		duration = &seconds
	}
	resolution, err := optionalString(inv.Args, "resolution")
	if err != nil {
		return mediaError(err.Error()), nil
	}
	aspect, err := optionalString(inv.Args, "aspect_ratio")
	if err != nil {
		return mediaError(err.Error()), nil
	}
	modelID := inv.Binding.Code.VideoModelID
	if modelID == "" {
		return mediaError("no video model is configured for agentarea/media"), nil
	}
	p := inv.Principal
	ws, err := workspace(p)
	if err != nil {
		return ToolOutput{}, err
	}
	model, err := s.d.Describer.Describe(ctx, modelsapi.Principal(p), modelID, modelsapi.KindVideo)
	if err != nil {
		return ToolOutput{}, err
	}
	if err := s.refuseAtSpendCap(ctx, p, t.budget); err != nil {
		return ToolOutput{}, err
	}
	var estimate *money.Decimal
	if model.Prices.VideoSecond != nil && duration != nil {
		v := model.Prices.VideoSecond.Mul(money.FromInt(int64(*duration)))
		estimate = &v
	}
	if estimate == nil && duration == nil && model.ManagedBy == domain.ManagedByPlatform && s.d.Billing != nil {
		return ToolOutput{}, s.refuseCall("duration_required", "a video on the platform's model is held by its length: pass duration")
	}
	f, err := s.holdModelCall(ctx, p, model, estimate, mediaHoldKey(inv.CallRef))
	if err != nil {
		return ToolOutput{}, err
	}
	submitted, err := s.d.Media.SubmitVideo(ctx, modelsapi.Principal(p), modelsapi.VideoSubmission{
		Model: model, Funded: f.platformFunded, Prompt: prompt, Duration: duration, Resolution: resolution, AspectRatio: aspect,
	})
	if err != nil {
		s.releaseHold(ctx, f, "the video was not submitted")
		return ToolOutput{}, err
	}
	stored, err := json.Marshal(storedFundingOf(f))
	if err != nil {
		s.releaseHold(ctx, f, "the video was not submitted")
		return ToolOutput{}, err
	}
	jobID, err := s.d.VideoJobs.CreateVideoJob(ctx, ws, p.UserID, modelsapi.NewVideoJob{
		ModelInstanceID: model.ModelID, TaskID: inv.TaskID, ProviderJobID: submitted.ProviderJobID, Prompt: prompt,
		Status: submitted.Status, Funding: stored,
	})
	if err != nil {
		s.releaseHold(ctx, f, "the video was not submitted")
		return ToolOutput{}, err
	}
	return ToolOutput{Success: true, Result: orderedJSON{{"job_id", jobID}, {"status", submitted.Status}}.String(), Source: "builtin"}, nil
}

// videoState answers a job that has no file to report: still running, or ended with its error.
func videoState(jobID, status, errText string) ToolOutput {
	if errText != "" {
		return ToolOutput{Result: orderedJSON{{"job_id", jobID}, {"status", status}, {"error", errText}}.String(), Error: errText, Source: "builtin"}
	}
	return ToolOutput{Success: true, Result: orderedJSON{{"job_id", jobID}, {"status", status}}.String(), Source: "builtin"}
}

func (t mediaTools) getVideo(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	s := t.s
	jobID, err := stringArg(inv.Args, "job_id")
	if err != nil {
		return ToolOutput{}, err
	}
	p := inv.Principal
	ws, err := workspace(p)
	if err != nil {
		return ToolOutput{}, err
	}
	job, ok, err := s.d.VideoJobs.VideoJobOfTask(ctx, ws, jobID, inv.TaskID)
	if err != nil {
		return ToolOutput{}, err
	}
	if !ok {
		return mediaError(fmt.Sprintf("no video job %s was submitted by this task", jobID)), nil
	}
	if job.FilePath != "" {
		out := ToolOutput{Success: true, ArtifactPaths: []string{job.FilePath}, Source: "builtin",
			Result: orderedJSON{{"job_id", jobID}, {"status", modelsapi.VideoCompleted}, {"file_path", job.FilePath}}.String()}
		// A retry of the call that billed it reports the line again; the run keeps one result per call.
		if job.BilledCallRef == inv.CallRef && len(job.Billing) > 0 {
			line, err := chargeLineOf(job.Billing)
			if err != nil {
				return ToolOutput{}, err
			}
			out.ModelCost, out.ModelBilling, out.CostUnknown = line.Amount, &line, line.CostUnknown
		}
		return out, nil
	}
	if modelsapi.VideoEnded(job.Status) {
		return videoState(jobID, job.Status, job.Error), nil
	}
	if len(job.Funding) == 0 {
		return mediaError(fmt.Sprintf("video job %s was submitted before jobs kept their funding; it cannot be checked on this credential", jobID)), nil
	}
	f, err := restoreFunding(job.Funding)
	if err != nil {
		return ToolOutput{}, fmt.Errorf("video job %s: %w", jobID, err)
	}
	model, err := s.d.Describer.Describe(ctx, modelsapi.Principal(p), job.ModelInstanceID, modelsapi.KindVideo)
	if err != nil {
		return ToolOutput{}, err
	}
	call := modelsapi.VideoJobCall{Model: model, Funded: f.platformFunded, ProviderJobID: job.ProviderJobID}
	progress, err := s.d.Media.VideoStatus(ctx, modelsapi.Principal(p), call)
	if err != nil {
		return ToolOutput{}, err
	}
	switch {
	case modelsapi.VideoRunning(progress.Status):
		if progress.Status != job.Status {
			if err := s.d.VideoJobs.SetVideoJobStatus(ctx, ws, jobID, progress.Status, ""); err != nil {
				return ToolOutput{}, err
			}
		}
		return videoState(jobID, progress.Status, ""), nil
	case modelsapi.VideoEnded(progress.Status):
		errText := progress.Error
		if errText == "" {
			errText = "the provider reports the job " + progress.Status
		}
		if err := s.d.VideoJobs.SetVideoJobStatus(ctx, ws, jobID, progress.Status, errText); err != nil {
			return ToolOutput{}, err
		}
		s.releaseHold(ctx, f, "video job "+jobID+" failed")
		return videoState(jobID, progress.Status, errText), nil
	case progress.Status != modelsapi.VideoCompleted:
		return ToolOutput{}, &modelsapi.ModelCallError{Msg: fmt.Sprintf("video job %s has unhandled status '%s'", jobID, progress.Status)}
	}
	video, err := s.d.Media.VideoContent(ctx, modelsapi.Principal(p), call)
	if err != nil {
		return ToolOutput{}, err
	}
	charge, err := t.charge(ctx, f, progress.CostUSD)
	if err != nil {
		return ToolOutput{}, err
	}
	path := mediaDir + "/video-" + jobID + mediaExtension(video.MediaType)
	if _, err := s.d.Runtime.PutFile(ctx, p.WorkspaceID, filesTask(inv), path, video.Content); err != nil {
		return ToolOutput{}, fmt.Errorf("the finished video could not be saved: %w", err)
	}
	billing, err := json.Marshal(storedBillingOf(charge))
	if err != nil {
		return ToolOutput{}, err
	}
	amount := charge.Amount
	billed, err := s.d.VideoJobs.RecordVideoSaved(ctx, ws, jobID, modelsapi.SavedVideo{
		FilePath: path, CostUSD: progress.CostUSD, BilledCost: &amount, Billing: billing, CallRef: inv.CallRef,
	})
	if err != nil {
		return ToolOutput{}, err
	}
	out := ToolOutput{Success: true, ArtifactPaths: []string{path}, Source: "builtin", Result: orderedJSON{
		{"job_id", jobID}, {"status", modelsapi.VideoCompleted}, {"file_path", path}, {"media_type", video.MediaType}, {"size", len(video.Content)},
	}.String()}
	// Another call already reported this generation's line.
	if billed {
		out.ModelCost, out.ModelBilling, out.CostUnknown = charge.Amount, &charge, charge.CostUnknown
	}
	return out, nil
}

// storedFunding is ModelFunding.stored(): what a video job keeps to finish its call later.
type storedFunding struct {
	ModelInstanceID    string  `json:"model_instance_id"`
	PlatformFunded     *bool   `json:"platform_funded"`
	HoldID             *string `json:"hold_id"`
	HeldAmount         *string `json:"held_amount"`
	HeldCurrency       *string `json:"held_currency"`
	VendorCostEstimate *string `json:"vendor_cost_estimate"`
}

func storedFundingOf(f funding) storedFunding {
	platform := f.platformFunded
	out := storedFunding{ModelInstanceID: f.modelID, PlatformFunded: &platform}
	if f.holdID != "" {
		hold, held, currency, estimate := f.holdID, f.held.String(), f.heldCurrency, f.estimate.String()
		out.HoldID, out.HeldAmount, out.HeldCurrency, out.VendorCostEstimate = &hold, &held, &currency, &estimate
	}
	return out
}

// restoreFunding is ModelFunding.restore.
func restoreFunding(raw []byte) (funding, error) {
	var st storedFunding
	if err := json.Unmarshal(raw, &st); err != nil {
		return funding{}, fmt.Errorf("its funding is not a stored funding: %w", err)
	}
	if st.ModelInstanceID == "" || st.PlatformFunded == nil {
		return funding{}, errors.New("its funding names no model instance or payer")
	}
	f := funding{modelID: st.ModelInstanceID, platformFunded: *st.PlatformFunded}
	if st.HoldID == nil || *st.HoldID == "" {
		return f, nil
	}
	f.holdID = *st.HoldID
	if st.HeldCurrency != nil {
		f.heldCurrency = *st.HeldCurrency
	}
	for _, v := range []struct {
		raw *string
		to  *money.Decimal
	}{{st.HeldAmount, &f.held}, {st.VendorCostEstimate, &f.estimate}} {
		if v.raw == nil {
			continue
		}
		d, err := money.Parse(*v.raw)
		if err != nil {
			return funding{}, fmt.Errorf("its funding has an amount that is not a number: %w", err)
		}
		*v.to = d
	}
	return f, nil
}

// storedBilling is ModelCharge.as_billing(): the line a saved video reported.
type storedBilling struct {
	Amount          string  `json:"amount"`
	Currency        string  `json:"currency"`
	VendorCost      string  `json:"vendor_cost"`
	VendorCurrency  string  `json:"vendor_currency"`
	Estimate        bool    `json:"estimate"`
	Settle          *string `json:"settle"`
	HoldID          *string `json:"hold_id"`
	CostUnknown     bool    `json:"cost_unknown"`
	Payer           string  `json:"payer"`
	ModelInstanceID string  `json:"model_instance_id"`
}

func storedBillingOf(c ChargeLine) storedBilling {
	out := storedBilling{
		Amount: c.Amount.String(), Currency: c.Currency, VendorCost: c.VendorCost.String(), VendorCurrency: c.VendorCurrency,
		Estimate: c.Estimate, CostUnknown: c.CostUnknown, Payer: c.Payer, ModelInstanceID: c.ModelInstanceID,
	}
	if c.Settle != "" {
		settle := c.Settle
		out.Settle = &settle
	}
	if c.HoldID != "" {
		hold := c.HoldID
		out.HoldID = &hold
	}
	return out
}

func chargeLineOf(raw []byte) (ChargeLine, error) {
	var st storedBilling
	if err := json.Unmarshal(raw, &st); err != nil {
		return ChargeLine{}, fmt.Errorf("a saved video's billing is not a spend line: %w", err)
	}
	amount, err := money.Parse(st.Amount)
	if err != nil {
		return ChargeLine{}, fmt.Errorf("a saved video's billing amount: %w", err)
	}
	vendor, err := money.Parse(st.VendorCost)
	if err != nil {
		return ChargeLine{}, fmt.Errorf("a saved video's vendor cost: %w", err)
	}
	line := ChargeLine{
		ModelInstanceID: st.ModelInstanceID, Amount: amount, Currency: st.Currency, VendorCost: vendor, VendorCurrency: st.VendorCurrency,
		Estimate: st.Estimate, CostUnknown: st.CostUnknown, Payer: st.Payer, PlatformFunded: st.Payer == domain.PayerPlatform,
	}
	if st.Settle != nil {
		line.Settle = *st.Settle
	}
	if st.HoldID != nil {
		line.HoldID = *st.HoldID
	}
	return line, nil
}
