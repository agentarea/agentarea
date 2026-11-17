package service

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"net/url"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/transport"
)

// maxVideoBytes is MAX_VIDEO_BYTES: a larger video is refused rather than held in memory.
const maxVideoBytes = 512 * 1024 * 1024

var _ api.Media = (*Service)(nil)

// mediaCall is one HTTP call to a media model's endpoint: the address and the credential
// resolved as the decision call resolves them, the answer's body never repeated.
type mediaCall struct {
	what, kind string
	model      api.ResolvedModel
	funded     bool
	method     string
	path       string
	query      url.Values
	body       any
}

func (s *Service) mediaDo(ctx context.Context, p api.Principal, c mediaCall) (*http.Response, context.CancelFunc, error) {
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return nil, nil, err
	}
	m := c.model
	profile, err := profileOf(m.Provider)
	if err != nil {
		return nil, nil, err
	}
	target := profile.APIURL(s.localEndpoint(m.EndpointURL), c.path)
	if target == "" {
		return nil, nil, &api.ModelCallError{Msg: fmt.Sprintf("model instance %s uses provider '%s', which has no public address, and has no endpoint_url configured", m.ModelID, m.ProviderType)}
	}
	if len(c.query) > 0 {
		target += "?" + c.query.Encode()
	}
	key, err := s.apiKey(ctx, ws, p.UserID, m.APIKeySecret, m.ManagedBy, c.funded)
	if err != nil {
		return nil, nil, err
	}
	var body io.Reader
	if c.body != nil {
		var buf bytes.Buffer
		enc := json.NewEncoder(&buf)
		enc.SetEscapeHTML(false)
		if err := enc.Encode(c.body); err != nil {
			return nil, nil, err
		}
		body = &buf
	}
	cctx, cancel := context.WithTimeout(ctx, mediaTimeout)
	req, err := http.NewRequestWithContext(cctx, c.method, target, body)
	if err != nil {
		cancel()
		return nil, nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range profile.Headers(key) {
		req.Header.Set(k, v)
	}
	resp, err := (&http.Client{Transport: s.roundTripper(m.ManagedBy), CheckRedirect: transport.NoRedirects}).Do(req)
	if err != nil {
		cancel()
		if errors.Is(err, netguard.ErrUnsafe) {
			slog.WarnContext(ctx, "Media model endpoint refused by the outbound policy", "what", c.what, "error", err.Error())
			return nil, nil, &api.ModelCallError{Msg: c.kind + " model endpoint points to an address this deployment does not call"}
		}
		if ctx.Err() != nil {
			return nil, nil, ctx.Err()
		}
		slog.WarnContext(ctx, "Media model call got no answer", "what", c.what, "error", err.Error())
		return nil, nil, callFailed(c.what, 0)
	}
	if resp.StatusCode/100 != 2 {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 500))
		_ = resp.Body.Close()
		cancel()
		slog.WarnContext(ctx, "media model endpoint answered an error", "what", c.what, "status", resp.StatusCode, "body", string(raw))
		return nil, nil, callFailed(c.what, resp.StatusCode)
	}
	return resp, cancel, nil
}

// mediaJSON is a media call answered with a JSON object (_json_object).
func (s *Service) mediaJSON(ctx context.Context, p api.Principal, c mediaCall) (map[string]any, error) {
	resp, cancel, err := s.mediaDo(ctx, p, c)
	if err != nil {
		return nil, err
	}
	defer cancel()
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return nil, callFailed(c.what, 0)
	}
	var payload any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&payload); err != nil {
		return nil, &api.ModelCallError{Msg: c.what + " returned a body that is not JSON"}
	}
	obj, ok := payload.(map[string]any)
	if !ok {
		return nil, &api.ModelCallError{Msg: c.what + " returned a body that is not a JSON object"}
	}
	return obj, nil
}

// reportedCost is the usage's cost as the provider reported it; nil when it reported none.
func reportedCost(payload map[string]any) (*money.Decimal, error) {
	u, present := payload["usage"]
	if !present || u == nil {
		return nil, nil
	}
	usage, ok := u.(map[string]any)
	if !ok {
		return nil, &api.ModelCallError{Msg: "response usage is not an object"}
	}
	c, present := usage["cost"]
	if !present || c == nil {
		return nil, nil
	}
	d, err := money.Parse(fmt.Sprint(c))
	if err != nil {
		return nil, &api.ModelCallError{Msg: "response reported a cost that is not a number"}
	}
	return &d, nil
}

// GenerateImage is ImageModel.generate: one image as base64, its cost reported or the spec's
// per-image price.
func (s *Service) GenerateImage(ctx context.Context, p api.Principal, c api.ImageCall) (api.GeneratedMedia, error) {
	body := map[string]any{"model": c.Model.ModelName, "prompt": c.Prompt, "n": 1, "response_format": "b64_json"}
	if c.Size != "" {
		body["size"] = c.Size
	}
	payload, err := s.mediaJSON(ctx, p, mediaCall{what: "image generation", kind: "image", model: c.Model, funded: c.Funded,
		method: http.MethodPost, path: "/images/generations", body: body})
	if err != nil {
		return api.GeneratedMedia{}, err
	}
	return imageReply(c.Model, payload)
}

func imageReply(m api.ResolvedModel, payload map[string]any) (api.GeneratedMedia, error) {
	var encoded string
	if data, ok := payload["data"].([]any); ok && len(data) > 0 {
		if first, ok := data[0].(map[string]any); ok {
			encoded, _ = first["b64_json"].(string)
		}
	}
	if encoded == "" {
		return api.GeneratedMedia{}, &api.ModelCallError{Msg: "image model returned no image bytes"}
	}
	content, err := base64.StdEncoding.Strict().DecodeString(encoded)
	if err != nil {
		return api.GeneratedMedia{}, &api.ModelCallError{Msg: "image model returned malformed base64"}
	}
	mediaType, err := imageMediaType(content)
	if err != nil {
		return api.GeneratedMedia{}, err
	}
	cost, err := reportedCost(payload)
	if err != nil {
		return api.GeneratedMedia{}, err
	}
	if cost == nil {
		if m.Prices.Image == nil {
			slog.Error("Image model instance reported no cost and its spec has no per-image price; the call's cost is unknown",
				"model_id", m.ModelID, "model_name", m.ModelName)
		} else {
			price := *m.Prices.Image
			cost = &price
		}
	}
	return api.GeneratedMedia{Content: content, MediaType: mediaType, CostUSD: cost}, nil
}

// imageMediaType is _image_media_type: the type the bytes' signature names.
func imageMediaType(b []byte) (string, error) {
	switch {
	case bytes.HasPrefix(b, []byte("\x89PNG\r\n\x1a\n")):
		return "image/png", nil
	case bytes.HasPrefix(b, []byte("\xff\xd8\xff")):
		return "image/jpeg", nil
	case bytes.HasPrefix(b, []byte("GIF87a")), bytes.HasPrefix(b, []byte("GIF89a")):
		return "image/gif", nil
	case len(b) >= 12 && string(b[:4]) == "RIFF" && string(b[8:12]) == "WEBP":
		return "image/webp", nil
	}
	return "", &api.ModelCallError{Msg: "image model returned bytes that are not a PNG, JPEG, GIF or WebP image"}
}

func videoStatus(payload map[string]any) (string, error) {
	raw, _ := payload["status"].(string)
	switch raw {
	case api.VideoPending, api.VideoInProgress, api.VideoCompleted, api.VideoFailed, api.VideoCancelled, api.VideoExpired:
		return raw, nil
	}
	return "", &api.ModelCallError{Msg: fmt.Sprintf("video job has unknown status %v", payload["status"])}
}

// SubmitVideo is VideoModel.submit.
func (s *Service) SubmitVideo(ctx context.Context, p api.Principal, v api.VideoSubmission) (api.SubmittedVideo, error) {
	body := map[string]any{"model": v.Model.ModelName, "prompt": v.Prompt}
	if v.Duration != nil {
		body["duration"] = *v.Duration
	}
	if v.Resolution != "" {
		body["resolution"] = v.Resolution
	}
	if v.AspectRatio != "" {
		body["aspect_ratio"] = v.AspectRatio
	}
	payload, err := s.mediaJSON(ctx, p, mediaCall{what: "video submission", kind: "video", model: v.Model, funded: v.Funded,
		method: http.MethodPost, path: "/videos", body: body})
	if err != nil {
		return api.SubmittedVideo{}, err
	}
	id, _ := payload["id"].(string)
	if id == "" {
		return api.SubmittedVideo{}, &api.ModelCallError{Msg: "video submission returned no job id"}
	}
	status, err := videoStatus(payload)
	if err != nil {
		return api.SubmittedVideo{}, err
	}
	return api.SubmittedVideo{ProviderJobID: id, Status: status}, nil
}

// VideoStatus is VideoModel.status.
func (s *Service) VideoStatus(ctx context.Context, p api.Principal, c api.VideoJobCall) (api.VideoProgress, error) {
	payload, err := s.mediaJSON(ctx, p, mediaCall{what: "video status", kind: "video", model: c.Model, funded: c.Funded,
		method: http.MethodGet, path: "/videos/" + url.PathEscape(c.ProviderJobID)})
	if err != nil {
		return api.VideoProgress{}, err
	}
	status, err := videoStatus(payload)
	if err != nil {
		return api.VideoProgress{}, err
	}
	cost, err := reportedCost(payload)
	if err != nil {
		return api.VideoProgress{}, err
	}
	return api.VideoProgress{Status: status, CostUSD: cost, Error: errorText(payload["error"])}, nil
}

// errorText is _error_text: a job's error is documented both as a string and as {code, message}.
func errorText(v any) string {
	switch e := v.(type) {
	case nil:
		return ""
	case string:
		return e
	case map[string]any:
		if m, ok := e["message"]; ok && m != nil && m != "" {
			return fmt.Sprint(m)
		}
	}
	b, _ := json.Marshal(v)
	return string(b)
}

// VideoContent is VideoModel.content: the finished video, at most maxVideoBytes.
func (s *Service) VideoContent(ctx context.Context, p api.Principal, c api.VideoJobCall) (api.GeneratedMedia, error) {
	resp, cancel, err := s.mediaDo(ctx, p, mediaCall{what: "video download", kind: "video", model: c.Model, funded: c.Funded,
		method: http.MethodGet, path: "/videos/" + url.PathEscape(c.ProviderJobID) + "/content", query: url.Values{"index": {"0"}}})
	if err != nil {
		return api.GeneratedMedia{}, err
	}
	defer cancel()
	defer func() { _ = resp.Body.Close() }()
	contentType := resp.Header.Get("Content-Type")
	if contentType == "" {
		return api.GeneratedMedia{}, &api.ModelCallError{Msg: "video download returned no content type"}
	}
	mediaType, _, err := mime.ParseMediaType(contentType)
	if err != nil {
		mediaType = strings.TrimSpace(strings.SplitN(contentType, ";", 2)[0])
	}
	if !strings.HasPrefix(mediaType, "video/") {
		return api.GeneratedMedia{}, &api.ModelCallError{Msg: "video download returned " + mediaType}
	}
	content, err := io.ReadAll(io.LimitReader(resp.Body, maxVideoBytes+1))
	if err != nil {
		return api.GeneratedMedia{}, callFailed("video download", 0)
	}
	if len(content) > maxVideoBytes {
		return api.GeneratedMedia{}, &api.ModelCallError{Msg: fmt.Sprintf("video is larger than the %d-byte limit; refusing it", maxVideoBytes)}
	}
	return api.GeneratedMedia{Content: content, MediaType: mediaType}, nil
}
