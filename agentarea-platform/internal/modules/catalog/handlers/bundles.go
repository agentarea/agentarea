package handlers

import (
	"context"
	"errors"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/catalog"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/service"
)

// WithBundles mounts bundle analyze and install.
func (s *Server) WithBundles(b *service.Bundles) *Server {
	s.bundles = b
	return s
}

func analyzeBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	req, fes := service.ValidateAnalyzeRequest(o)
	*errs = append(*errs, fes...)
	in.analyze = req
}

func installBody(v any, in *input, errs fieldErrs) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	req, fes := service.ValidateInstallRequest(o)
	*errs = append(*errs, fes...)
	in.install = req
}

func bundleParseError(err error) error {
	var pe *service.BundleParseError
	if errors.As(err, &pe) {
		return httpx.HTTPError(http.StatusUnprocessableEntity, pe.Msg).Wrap(err)
	}
	return err
}

func (s *Server) AnalyzeBundleV1BundlesAnalyzePost(ctx context.Context, _ gen.AnalyzeBundleV1BundlesAnalyzePostRequestObject) (gen.AnalyzeBundleV1BundlesAnalyzePostResponseObject, error) {
	req := inputFrom(ctx).analyze
	var preview service.ImportPreview
	var err error
	switch {
	case req.Bundle != nil:
		preview, err = s.bundles.AnalyzeBundle(ctx, *req.Bundle, req.SetupValues, false, req.Target)
	case len(req.Files) > 0:
		preview, err = s.bundles.AnalyzeFiles(ctx, req.Files, req.SetupValues, req.Target)
	default:
		source := ""
		if req.Source != nil {
			source = *req.Source
		}
		if req.SourceURL != nil && *req.SourceURL != "" {
			source, err = s.bundles.FetchSource(ctx, *req.SourceURL)
			var se *service.BundleSourceError
			if errors.As(err, &se) {
				return nil, httpx.HTTPError(http.StatusBadRequest, se.Msg).Wrap(err)
			}
			if err != nil {
				return nil, err
			}
		}
		preview, err = s.bundles.AnalyzeText(ctx, source, req.SetupValues, req.Target)
	}
	if err != nil {
		return nil, bundleParseError(err)
	}
	return ok(preview.Dump()), nil
}

func bundleProblem(status int, code, msg string, issues []service.PreviewIssue) *httpx.Error {
	return httpx.NewError(status, code, msg).With("issues", service.IssueDumps(issues))
}

func (s *Server) InstallBundleV1BundlesInstallPost(ctx context.Context, _ gen.InstallBundleV1BundlesInstallPostRequestObject) (gen.InstallBundleV1BundlesInstallPostResponseObject, error) {
	req := inputFrom(ctx).install
	result, err := s.bundles.Install(ctx, req.Bundle, req.SetupValues, req.PlanDigest, req.Target)
	if err == nil {
		out := result.Dump()
		out.Set("install_id", *result.InstalledBundleID)
		return ok(out), nil
	}
	var be *service.BundleError
	if errors.As(err, &be) {
		switch be.Kind {
		case service.BundlePlanChanged:
			return nil, bundleProblem(http.StatusConflict, "bundle_plan_changed", be.Msg, be.Issues).Wrap(err)
		case service.BundleInvalid:
			return nil, bundleProblem(http.StatusUnprocessableEntity, "bundle_invalid", be.Msg, be.Issues).Wrap(err)
		case service.BundleInstallFailed:
		}
		return nil, bundleProblem(http.StatusBadRequest, "bundle_install_failed", be.Msg, be.Issues).Wrap(err)
	}
	if s.errs != nil {
		if e, _ := s.errs.Resolve(err); e.Status == http.StatusBadRequest || e.Status == http.StatusUnprocessableEntity {
			return nil, bundleProblem(http.StatusBadRequest, "bundle_install_failed", e.Detail, nil).Wrap(err)
		}
	}
	return nil, err
}
