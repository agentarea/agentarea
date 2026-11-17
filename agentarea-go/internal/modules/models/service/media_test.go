package service

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
)

type mediaEndpoint struct {
	status      int
	contentType string
	body        string
}

func mediaServer(t *testing.T, routes map[string]*mediaEndpoint, seen map[string]map[string]any) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key := r.Method + " " + r.URL.Path
		if r.Body != nil {
			raw, _ := io.ReadAll(r.Body)
			if len(raw) > 0 {
				var body map[string]any
				_ = json.Unmarshal(raw, &body)
				seen[key] = body
			}
		}
		e, ok := routes[key]
		if !ok {
			http.NotFound(w, r)
			return
		}
		ct := e.contentType
		if ct == "" {
			ct = "application/json"
		}
		w.Header().Set("Content-Type", ct)
		w.WriteHeader(e.status)
		_, _ = io.WriteString(w, e.body)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func mediaModel(endpoint string) api.ResolvedModel {
	return api.ResolvedModel{ModelID: uuid.NewString(), ModelName: "m", ProviderType: "openai", EndpointURL: endpoint}
}

func TestAnImageCostsWhatTheProviderReportedElseItsPriceElseIsUnknown(t *testing.T) {
	e := newEnv(t)
	png := append([]byte("\x89PNG\r\n\x1a\n"), 1, 2, 3)
	b64 := base64.StdEncoding.EncodeToString(png)
	image := &mediaEndpoint{status: 200}
	seen := map[string]map[string]any{}
	srv := mediaServer(t, map[string]*mediaEndpoint{"POST /v1/images/generations": image}, seen)
	p := api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}
	price := money.MustParse("0.02")
	model := mediaModel(srv.URL)
	model.Prices.Image = &price

	image.body = `{"data": [{"b64_json": "` + b64 + `"}], "usage": {"cost": 0.04}}`
	got, err := e.svc.GenerateImage(context.Background(), p, api.ImageCall{Model: model, Prompt: "a cat", Size: "1024x1024"})
	if err != nil || got.MediaType != "image/png" || string(got.Content) != string(png) || !got.CostUSD.Equal(money.MustParse("0.04")) {
		t.Fatalf("reported: %+v %v", got, err)
	}
	if body := seen["POST /v1/images/generations"]; body["prompt"] != "a cat" || body["size"] != "1024x1024" || body["response_format"] != "b64_json" {
		t.Fatalf("request body %v", body)
	}

	image.body = `{"data": [{"b64_json": "` + b64 + `"}]}`
	got, err = e.svc.GenerateImage(context.Background(), p, api.ImageCall{Model: model, Prompt: "a cat"})
	if err != nil || !got.CostUSD.Equal(price) {
		t.Fatalf("priced: %+v %v", got, err)
	}
	if _, sized := seen["POST /v1/images/generations"]["size"]; sized {
		t.Fatal("an image with no size hint sent one")
	}

	model.Prices.Image = nil
	got, err = e.svc.GenerateImage(context.Background(), p, api.ImageCall{Model: model, Prompt: "a cat"})
	if err != nil || got.CostUSD != nil {
		t.Fatalf("unknown: %+v %v", got, err)
	}

	image.body = `{"data": [{"b64_json": "` + base64.StdEncoding.EncodeToString([]byte("<html>")) + `"}]}`
	if _, err = e.svc.GenerateImage(context.Background(), p, api.ImageCall{Model: model, Prompt: "a cat"}); err == nil ||
		err.Error() != "image model returned bytes that are not a PNG, JPEG, GIF or WebP image" {
		t.Fatalf("not an image: %v", err)
	}

	image.status, image.body = 400, `{"error": "upstream secret sk-live-123"}`
	_, err = e.svc.GenerateImage(context.Background(), p, api.ImageCall{Model: model, Prompt: "a cat"})
	var callErr *api.ModelCallError
	if !errors.As(err, &callErr) || callErr.Msg != "image generation failed: HTTP 400" || strings.Contains(err.Error(), "sk-live") {
		t.Fatalf("failure: %v", err)
	}
}

func TestAVideoIsSubmittedPolledAndDownloadedWithoutEchoingTheEndpoint(t *testing.T) {
	e := newEnv(t)
	submit := &mediaEndpoint{status: 200, body: `{"id": "job-1", "status": "pending"}`}
	status := &mediaEndpoint{status: 200, body: `{"status": "in_progress"}`}
	content := &mediaEndpoint{status: 200, contentType: "video/mp4", body: "MP4DATA"}
	seen := map[string]map[string]any{}
	srv := mediaServer(t, map[string]*mediaEndpoint{
		"POST /v1/videos": submit, "GET /v1/videos/job-1": status, "GET /v1/videos/job-1/content": content,
	}, seen)
	p := api.Principal{WorkspaceID: e.ws.ID(), UserID: "u1"}
	model := mediaModel(srv.URL)
	ctx := context.Background()

	seconds := 5
	sub, err := e.svc.SubmitVideo(ctx, p, api.VideoSubmission{Model: model, Prompt: "waves", Duration: &seconds, AspectRatio: "16:9"})
	if err != nil || sub.ProviderJobID != "job-1" || sub.Status != api.VideoPending {
		t.Fatalf("submit: %+v %v", sub, err)
	}
	if body := seen["POST /v1/videos"]; body["duration"] != float64(5) || body["aspect_ratio"] != "16:9" || body["resolution"] != nil {
		t.Fatalf("submit body %v", body)
	}
	call := api.VideoJobCall{Model: model, ProviderJobID: "job-1"}
	running, err := e.svc.VideoStatus(ctx, p, call)
	if err != nil || running.Status != api.VideoInProgress || running.CostUSD != nil {
		t.Fatalf("running: %+v %v", running, err)
	}
	status.body = `{"status": "completed", "usage": {"cost": "1.5"}}`
	done, err := e.svc.VideoStatus(ctx, p, call)
	if err != nil || done.Status != api.VideoCompleted || !done.CostUSD.Equal(money.MustParse("1.5")) {
		t.Fatalf("reported: %+v %v", done, err)
	}
	status.body = `{"status": "completed"}`
	if unknown, err := e.svc.VideoStatus(ctx, p, call); err != nil || unknown.CostUSD != nil {
		t.Fatalf("unknown cost: %+v %v", unknown, err)
	}
	status.body = `{"status": "failed", "error": {"code": 1, "message": "content policy"}}`
	if failed, err := e.svc.VideoStatus(ctx, p, call); err != nil || !api.VideoEnded(failed.Status) || failed.Error != "content policy" {
		t.Fatalf("failed: %+v %v", failed, err)
	}
	status.body = `{"status": "queued"}`
	if _, err := e.svc.VideoStatus(ctx, p, call); err == nil || err.Error() != "video job has unknown status queued" {
		t.Fatalf("unknown status: %v", err)
	}
	video, err := e.svc.VideoContent(ctx, p, call)
	if err != nil || video.MediaType != "video/mp4" || string(video.Content) != "MP4DATA" {
		t.Fatalf("content: %+v %v", video, err)
	}
	content.contentType = "text/html; charset=utf-8"
	if _, err := e.svc.VideoContent(ctx, p, call); err == nil || err.Error() != "video download returned text/html" {
		t.Fatalf("not a video: %v", err)
	}

	submit.status, submit.body = 502, `upstream said: key sk-live-456 is over quota`
	_, err = e.svc.SubmitVideo(ctx, p, api.VideoSubmission{Model: model, Prompt: "waves"})
	if err == nil || err.Error() != "video submission failed: HTTP 502" || strings.Contains(err.Error(), "sk-live") {
		t.Fatalf("submit failure: %v", err)
	}
}
