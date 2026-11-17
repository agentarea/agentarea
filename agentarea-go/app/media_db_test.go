package app

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	runsservice "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

type mediaDescriber struct {
	models map[string]modelsapi.ResolvedModel
}

func (d mediaDescriber) Describe(_ context.Context, _ modelsapi.Principal, id, kind string) (modelsapi.ResolvedModel, error) {
	m, ok := d.models[id+"/"+kind]
	if !ok {
		return modelsapi.ResolvedModel{}, modelsapi.ErrNotFound
	}
	return m, nil
}

type mediaModels struct {
	mu        sync.Mutex
	status    modelsapi.VideoProgress
	funded    []bool
	downloads int
}

func (m *mediaModels) GenerateImage(_ context.Context, _ modelsapi.Principal, c modelsapi.ImageCall) (modelsapi.GeneratedMedia, error) {
	cost := money.MustParse("0.04")
	m.funded = append(m.funded, c.Funded)
	return modelsapi.GeneratedMedia{Content: []byte("\x89PNG\r\n\x1a\nimg"), MediaType: "image/png", CostUSD: &cost}, nil
}

func (m *mediaModels) SubmitVideo(_ context.Context, _ modelsapi.Principal, v modelsapi.VideoSubmission) (modelsapi.SubmittedVideo, error) {
	m.funded = append(m.funded, v.Funded)
	return modelsapi.SubmittedVideo{ProviderJobID: "prov-1", Status: modelsapi.VideoPending}, nil
}

func (m *mediaModels) VideoStatus(_ context.Context, _ modelsapi.Principal, c modelsapi.VideoJobCall) (modelsapi.VideoProgress, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.funded = append(m.funded, c.Funded)
	return m.status, nil
}

func (m *mediaModels) VideoContent(context.Context, modelsapi.Principal, modelsapi.VideoJobCall) (modelsapi.GeneratedMedia, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.downloads++
	return modelsapi.GeneratedMedia{Content: []byte("MP4"), MediaType: "video/mp4"}, nil
}

type mediaBilling struct {
	mu     sync.Mutex
	holds  []money.AuthorizeRequest
	quotes int
	voided []string
}

func (b *mediaBilling) Currency() money.Currency { return "EUR" }

func (b *mediaBilling) Authorize(_ context.Context, req money.AuthorizeRequest) (money.HoldDecision, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.holds = append(b.holds, req)
	held := money.MustParse("0.6")
	return money.HoldDecision{Allowed: true, HoldID: "hold-" + req.Tool[:8], Amount: &held, Currency: "EUR"}, nil
}

func (b *mediaBilling) Capture(context.Context, money.CaptureRequest) (money.Charge, error) {
	panic("a tool call never captures")
}

func (b *mediaBilling) Void(_ context.Context, holdID string) error {
	b.voided = append(b.voided, holdID)
	return nil
}

func (b *mediaBilling) Quote(_ context.Context, lines []money.QuoteLine) ([]money.Quote, error) {
	b.quotes++
	out := make([]money.Quote, len(lines))
	for i, l := range lines {
		amount := l.VendorCost.Mul(money.MustParse("1.1"))
		out[i] = money.Quote{Amount: &amount}
	}
	return out, nil
}

type mediaRuntime struct {
	sandboxapi.Runtime
	files map[string][]byte
}

func (r *mediaRuntime) PutFile(_ context.Context, _, taskID, path string, data []byte) (sandboxapi.StoredFile, error) {
	r.files[taskID+"/"+path] = data
	return sandboxapi.StoredFile{}, nil
}

type eurDeployment struct{}

func (eurDeployment) Currency() money.Currency { return "EUR" }

func TestMediaToolsBillAnImageAndAVideoOnceAcrossItsPolls(t *testing.T) {
	d := pulseDB(t)
	ctx := context.Background()
	p := runsservice.Principal{WorkspaceID: uuid.NewString(), UserID: "user-1", AgentID: uuid.NewString()}
	ws, _ := scope.NewWorkspace(p.WorkspaceID, "")
	spec, modelSpec, config, videoID, imageID := uuid.New(), uuid.New(), uuid.New(), uuid.NewString(), uuid.NewString()
	err := d.Write(ctx, ws, func(ctx context.Context, s db.Session) error {
		for _, q := range []struct {
			sql  string
			args []any
		}{
			{`INSERT INTO provider_specs (id, provider_key, name, provider_type, is_builtin, workspace_id, created_by)
				VALUES ($1, 'openrouter', 'OpenRouter', 'openrouter', true, 'platform', 'system')`, []any{spec}},
			{`INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, is_active, workspace_id, created_by, kind)
				VALUES ($1, $2, 'veo', 'Veo', true, 'platform', 'system', 'video')`, []any{modelSpec, spec}},
			{`INSERT INTO provider_configs (id, provider_spec_id, name, is_active, is_public, workspace_id, created_by, managed_by)
				VALUES ($1, $2, 'platform', true, true, 'platform', 'system', 'platform')`, []any{config, spec}},
			{`INSERT INTO model_instances (id, provider_config_id, model_spec_id, name, is_active, is_public, workspace_id, created_by)
				VALUES ($1, $2, $3, 'veo', true, true, 'platform', 'system')`, []any{videoID, config, modelSpec}},
		} {
			if _, err := s.Q().Exec(ctx, q.sql, q.args...); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	imagePrice, secondPrice := money.MustParse("0.05"), money.MustParse("0.1")
	describer := mediaDescriber{models: map[string]modelsapi.ResolvedModel{
		imageID + "/image": {ModelID: imageID, ModelName: "img", ManagedBy: modelsapi.ManagedByPlatform, Prices: modelsapi.ModelPrices{Image: &imagePrice}},
		videoID + "/video": {ModelID: videoID, ModelName: "veo", ManagedBy: modelsapi.ManagedByPlatform, Prices: modelsapi.ModelPrices{VideoSecond: &secondPrice}},
	}}
	media := &mediaModels{}
	bill := &mediaBilling{}
	rt := &mediaRuntime{files: map[string][]byte{}}
	svc := runsservice.New(runsservice.Deps{
		DB: d, Pricing: eurDeployment{}, Billing: bill, Describer: describer, Media: media,
		VideoJobs: models.New(models.Deps{DB: d}).VideoJobs(), Runtime: rt, Log: slog.New(slog.DiscardHandler),
	})
	taskID := uuid.NewString()
	call := func(id, method string, args map[string]any, attempt int) runsservice.ToolOutput {
		t.Helper()
		res, err := svc.ExecuteTool(ctx, p, runsservice.ToolCall{
			TaskID: taskID, ToolCallID: id, ToolName: "media_" + method, Args: args, Attempt: attempt,
			Binding: runsapi.ToolBinding{Source: "code", Code: &runsapi.CodeBinding{
				Namespace: "agentarea/media", Method: method, ImageModelID: imageID, VideoModelID: videoID}},
		})
		if err != nil {
			t.Fatal(err)
		}
		return res.Out
	}

	image := call("c1", "generate_image", map[string]any{"prompt": "a cat"}, 1)
	if !image.Success || len(image.ArtifactPaths) != 1 || !strings.HasPrefix(image.ArtifactPaths[0], "media/image-") ||
		!strings.HasSuffix(image.ArtifactPaths[0], ".png") || rt.files[taskID+"/"+image.ArtifactPaths[0]] == nil {
		t.Fatalf("image %+v", image)
	}
	if !image.ModelCost.Equal(money.MustParse("0.044")) || image.ModelBilling == nil || image.ModelBilling.HoldID != "hold-"+imageID[:8] ||
		image.ModelBilling.Payer != "platform" || image.ModelBilling.Settle != "capture" || image.ModelBilling.ModelInstanceID != imageID {
		t.Fatalf("image line %+v %+v", image, image.ModelBilling)
	}
	var shown map[string]any
	if err := json.Unmarshal([]byte(image.Result), &shown); err != nil || shown["file_path"] != image.ArtifactPaths[0] || shown["media_type"] != "image/png" {
		t.Fatalf("image result %s", image.Result)
	}

	submitted := call("c2", "generate_video", map[string]any{"prompt": "waves", "duration": float64(5)}, 1)
	var job struct {
		JobID  string `json:"job_id"`
		Status string `json:"status"`
	}
	if err := json.Unmarshal([]byte(submitted.Result), &job); err != nil || !submitted.Success || job.Status != "pending" || submitted.ModelBilling != nil {
		t.Fatalf("submitted %+v", submitted)
	}
	if len(bill.holds) != 2 || !bill.holds[1].VendorCost.Equal(money.MustParse("0.5")) {
		t.Fatalf("holds %+v", bill.holds)
	}
	var funding map[string]any
	readRow := func(query string, dest ...any) {
		t.Helper()
		s, release, err := d.Read(ctx, ws)
		if err != nil {
			t.Fatal(err)
		}
		defer release()
		if err := s.Q().QueryRow(ctx, query, job.JobID).Scan(dest...); err != nil {
			t.Fatal(err)
		}
	}
	var raw []byte
	readRow(`SELECT funding FROM video_generation_jobs WHERE id = $1`, &raw)
	if err := json.Unmarshal(raw, &funding); err != nil || funding["hold_id"] != "hold-"+videoID[:8] || funding["held_amount"] != "0.6" ||
		funding["held_currency"] != "EUR" || funding["vendor_cost_estimate"] != "0.5" || funding["platform_funded"] != true || funding["model_instance_id"] != videoID {
		t.Fatalf("stored funding %s", raw)
	}

	media.status = modelsapi.VideoProgress{Status: modelsapi.VideoInProgress}
	running := call("c3", "get_video", map[string]any{"job_id": job.JobID}, 1)
	if !running.Success || !strings.Contains(running.Result, `"in_progress"`) || running.ModelBilling != nil || len(running.ArtifactPaths) != 0 {
		t.Fatalf("running %+v", running)
	}
	var status string
	readRow(`SELECT status FROM video_generation_jobs WHERE id = $1`, &status)
	if status != "in_progress" {
		t.Fatalf("status %s", status)
	}

	cost := money.MustParse("0.4")
	media.status = modelsapi.VideoProgress{Status: modelsapi.VideoCompleted, CostUSD: &cost}
	done := call("c4", "get_video", map[string]any{"job_id": job.JobID}, 1)
	path := "media/video-" + job.JobID + ".mp4"
	if !done.Success || len(done.ArtifactPaths) != 1 || done.ArtifactPaths[0] != path || string(rt.files[taskID+"/"+path]) != "MP4" {
		t.Fatalf("done %+v", done)
	}
	if !done.ModelCost.Equal(money.MustParse("0.44")) || done.ModelBilling == nil || done.ModelBilling.HoldID != "hold-"+videoID[:8] ||
		!done.ModelBilling.VendorCost.Equal(cost) || done.ModelBilling.Payer != "platform" {
		t.Fatalf("done line %+v %+v", done, done.ModelBilling)
	}
	for i, funded := range media.funded {
		if !funded {
			t.Fatalf("call %d on the platform's model ran unfunded", i)
		}
	}

	retried := call("c4", "get_video", map[string]any{"job_id": job.JobID}, 2)
	if !retried.Success || retried.ArtifactPaths[0] != path || retried.ModelCost.String() != done.ModelCost.String() || retried.ModelBilling == nil ||
		!retried.ModelBilling.Amount.Equal(done.ModelBilling.Amount) || !retried.ModelBilling.VendorCost.Equal(done.ModelBilling.VendorCost) ||
		retried.ModelBilling.HoldID != done.ModelBilling.HoldID || retried.ModelBilling.Settle != done.ModelBilling.Settle ||
		retried.ModelBilling.Payer != done.ModelBilling.Payer || retried.ModelBilling.ModelInstanceID != done.ModelBilling.ModelInstanceID ||
		retried.ModelBilling.Currency != done.ModelBilling.Currency || !retried.ModelBilling.PlatformFunded || !retried.ModelBilling.Estimate {
		t.Fatalf("retry of the billing call %+v %+v", retried, retried.ModelBilling)
	}
	other := call("c5", "get_video", map[string]any{"job_id": job.JobID}, 1)
	if !other.Success || other.ArtifactPaths[0] != path || other.ModelBilling != nil || other.ModelCost.Sign() != 0 || other.CostUnknown {
		t.Fatalf("another call %+v", other)
	}
	var billedRef string
	readRow(`SELECT billed_call_ref FROM video_generation_jobs WHERE id = $1`, &billedRef)
	if billedRef != taskID+":c4" || media.downloads != 1 || bill.quotes != 2 || len(bill.voided) != 0 {
		t.Fatalf("billed by %q, %d downloads, %d quotes, voided %v", billedRef, media.downloads, bill.quotes, bill.voided)
	}

	missing := call("c6", "get_video", map[string]any{"job_id": uuid.NewString()}, 1)
	if missing.Success || !strings.HasPrefix(missing.Error, "no video job ") {
		t.Fatalf("another task's job %+v", missing)
	}
}
