package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

// skillInput is what the skill routes' parameters and bodies validated to.
type skillInput struct {
	list                       service.SkillListQuery
	page                       httpx.Pagination
	content, githubURL         *string
	name, description          *string
	member                     domain.SkillMember
	includeURLs, discard, redo bool
}

const (
	maxSkillDescription = 1000
	minInt32            = math.MinInt32
	maxInt32            = math.MaxInt32
)

func lastQuery(q map[string][]string, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

func queryBool(q map[string][]string, key string, def bool, errs *[]httpx.FieldError) bool {
	v, ok := lastQuery(q, key)
	if !ok {
		return def
	}
	b, valid := httpx.ParseBool(v)
	if !valid {
		*errs = append(*errs, httpx.BoolParsing("query", key))
		return def
	}
	return b
}

func listSkillsQuery(q map[string][]string, in *input, errs *[]httpx.FieldError) {
	var si skillInput
	p, err := httpx.ParsePagination(q)
	var ve *httpx.ValidationError
	if errors.As(err, &ve) {
		*errs = append(*errs, ve.Errors...)
	}
	si.page = p
	si.list = service.SkillListQuery{Offset: p.Offset(), Limit: p.Limit(), Search: p.Search}
	if v, ok := lastQuery(q, "source_type"); ok {
		si.list.SourceType = &v
	}
	if v, ok := lastQuery(q, "network_scope"); ok {
		si.list.NetworkScope = &v
	}
	if v, ok := lastQuery(q, "from_registry"); ok {
		if b, valid := httpx.ParseBool(v); valid {
			si.list.FromRegistry = &b
		} else {
			*errs = append(*errs, httpx.BoolParsing("query", "from_registry"))
		}
	}
	si.list.IncludeCatalog = queryBool(q, "include_catalog", true, errs)
	in.area = si
}

func boolQuery(key string, def bool, set func(*skillInput, bool)) func(q map[string][]string, in *input, errs *[]httpx.FieldError) {
	return func(q map[string][]string, in *input, errs *[]httpx.FieldError) {
		si, _ := in.area.(skillInput)
		set(&si, queryBool(q, key, def, errs))
		in.area = si
	}
}

func uploadQuery(q map[string][]string, in *input, errs *[]httpx.FieldError) {
	var si skillInput
	for _, f := range []struct {
		key string
		max int
		dst **string
	}{{"name", maxName, &si.name}, {"description", maxSkillDescription, &si.description}} {
		v, ok := lastQuery(q, f.key)
		if !ok {
			continue
		}
		if len([]rune(v)) > f.max {
			*errs = append(*errs, httpx.StringTooLong(f.max, "query", f.key))
			continue
		}
		*f.dst = &v
	}
	in.area = si
}

// createSkillBody is SkillCreateRequest: its fields, then model_post_init.
func createSkillBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	n := len(*errs)
	var si skillInput
	si.content, _ = str(o, "content", 0, 0, true, errs)
	si.githubURL, _ = str(o, "github_url", 0, 0, true, errs)
	si.name, _ = str(o, "name", 0, maxName, true, errs)
	si.description, _ = str(o, "description", 0, maxSkillDescription, true, errs)
	if len(*errs) > n {
		return
	}
	hasContent := si.content != nil && *si.content != ""
	hasURL := si.githubURL != nil && *si.githubURL != ""
	switch {
	case !hasContent && !hasURL:
		*errs = append(*errs, httpx.ValueError("Either 'content' or 'github_url' must be provided", "body"))
	case hasContent && hasURL:
		*errs = append(*errs, httpx.ValueError("Only one of 'content' or 'github_url' can be provided", "body"))
	}
	in.area = si
}

// updateSkillBody is SkillUpdateRequest; a null name or description leaves it.
func updateSkillBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var si skillInput
	si.name, _ = str(o, "name", 1, maxName, true, errs)
	si.description, _ = str(o, "description", 0, maxSkillDescription, true, errs)
	si.content, _ = str(o, "content", 0, 0, true, errs)
	in.area = si
}

func intField(o wirejson.Object, key string, def int64, errs *[]httpx.FieldError) int64 {
	v, ok := o.Get(key)
	if !ok {
		return def
	}
	var n int64
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			n = i
		} else if f, err := x.Float64(); err == nil && f == math.Trunc(f) && !math.IsInf(f, 0) {
			if f < minInt32 {
				*errs = append(*errs, httpx.GreaterThanEqual(minInt32, "body", key))
				return def
			}
			if f > maxInt32 {
				*errs = append(*errs, httpx.LessThanEqual(maxInt32, "body", key))
				return def
			}
			n = int64(f)
		} else if err == nil {
			*errs = append(*errs, httpx.IntFromFloat("body", key))
			return def
		} else {
			*errs = append(*errs, httpx.IntParsing("body", key))
			return def
		}
	case string:
		i, fe := httpx.ValidateInt(x, httpx.IntBounds{Ge: minInt32, HasGe: true, Le: maxInt32, HasLe: true}, "body", key)
		if fe != nil {
			*errs = append(*errs, *fe)
			return def
		}
		return i
	default:
		*errs = append(*errs, httpx.IntType("body", key))
		return def
	}
	if n < minInt32 {
		*errs = append(*errs, httpx.GreaterThanEqual(minInt32, "body", key))
		return def
	}
	if n > maxInt32 {
		*errs = append(*errs, httpx.LessThanEqual(maxInt32, "body", key))
		return def
	}
	return n
}

func laxBool(o wirejson.Object, key string, def bool, errs *[]httpx.FieldError) bool {
	v, ok := o.Get(key)
	if !ok {
		return def
	}
	switch x := v.(type) {
	case bool:
		return x
	case json.Number:
		switch x.String() {
		case "0":
			return false
		case "1":
			return true
		}
		*errs = append(*errs, httpx.BoolParsing("body", key))
	case string:
		if b, valid := httpx.ParseBool(x); valid {
			return b
		}
		*errs = append(*errs, httpx.BoolParsing("body", key))
	default:
		*errs = append(*errs, httpx.BoolType("body", key))
	}
	return def
}

// memberBody is SkillMemberAddRequest.
func memberBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	var si skillInput
	id, set := uuidField(o, "child_skill_id", errs)
	switch {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "child_skill_id"))
	case id == nil:
		if raw, _ := o.Get("child_skill_id"); raw == nil {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", "child_skill_id"}, Msg: "UUID input should be a string, bytes or UUID object"})
		}
	default:
		si.member.ChildSkillID = *id
	}
	si.member.Order = int32(intField(o, "order", 0, errs)) //nolint:gosec // bounded to int32 above
	si.member.IsRequired = laxBool(o, "is_required", true, errs)
	si.member.Dependencies = []string{}
	if raw, ok := o.Get("dependencies"); ok {
		arr, isArr := raw.([]any)
		if !isArr {
			*errs = append(*errs, httpx.ListType("body", "dependencies"))
		}
		for i, it := range arr {
			s, isStr := it.(string)
			if !isStr {
				*errs = append(*errs, httpx.StringType("body", "dependencies", i))
				continue
			}
			si.member.Dependencies = append(si.member.Dependencies, s)
		}
	}
	in.area = si
}

func mapSkillError(err error) (*httpx.Error, bool) {
	var (
		ve      *domain.SkillValueError
		fm      *service.SkillFrontmatterError
		gh      *domain.SkillGitHubError
		files   *service.SkillFilesError
		missing *service.SkillNotFoundError
		member  *service.SkillMemberNotFoundError
		file    *service.SkillFileNotFoundError
		edited  *service.SkillCustomizedError
		notFrom *service.SkillNotFromCatalogError
		managed *service.SkillBundleManagedError
	)
	switch {
	case errors.As(err, &managed):
		return httpx.NewError(http.StatusConflict, "skill_bundle_managed", managed.Error()), true
	case errors.As(err, &edited):
		return httpx.NewError(http.StatusConflict, "skill_customized", edited.Msg), true
	case errors.As(err, &notFrom):
		return httpx.NewError(http.StatusConflict, "skill_not_from_catalog", notFrom.Msg), true
	case errors.As(err, &files):
		return httpx.HTTPError(http.StatusNotFound, files.Msg), true
	case errors.As(err, &file):
		return httpx.HTTPError(http.StatusNotFound, file.Error()), true
	case errors.As(err, &fm):
		return httpx.HTTPError(http.StatusUnprocessableEntity, fm.Msg), true
	case errors.As(err, &ve):
		return httpx.HTTPError(http.StatusBadRequest, ve.Msg), true
	case errors.As(err, &gh):
		switch gh.Kind {
		case domain.SkillGitHubRateLimited:
			return httpx.HTTPError(http.StatusTooManyRequests, gh.Msg), true
		case domain.SkillGitHubNotFound:
			return httpx.HTTPError(http.StatusNotFound, gh.Msg), true
		case domain.SkillGitHubOther, domain.SkillGitHubInvalidURL:
		}
		return httpx.HTTPError(http.StatusBadRequest, gh.Msg), true
	case errors.Is(err, service.ErrSkillVersionNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Skill version not found"), true
	case errors.As(err, &missing):
		return httpx.NotFound(missing.Error()), true
	case errors.As(err, &member):
		return httpx.HTTPError(http.StatusNotFound, member.Error()), true
	}
	return nil, false
}

// skillUTCISO is utc_isoformat: a naive value read as UTC, microseconds only when set.
func skillUTCISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "Z"
}

// skillJSON is SkillResponse.from_skill.
func skillJSON(v service.SkillView) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: v.ID}, {Key: "name", Value: v.Name}, {Key: "slug", Value: v.Slug},
		{Key: "description", Value: orNil(v.Description)}, {Key: "source_type", Value: v.SourceType},
		{Key: "source_url", Value: orNil(v.SourceURL)}, {Key: "network_scope", Value: v.NetworkScope},
		{Key: "workspace_id", Value: v.WorkspaceID}, {Key: "created_at", Value: skillUTCISO(v.CreatedAt)},
		{Key: "updated_at", Value: skillUTCISO(v.UpdatedAt)}, {Key: "is_catalog", Value: v.IsCatalog},
		{Key: "registry_item_id", Value: orNil(v.RegistryItemID)}, {Key: "update_available", Value: v.UpdateAvailable},
		{Key: "customized", Value: domain.SkillIsCustomized(v.Skill)}, {Key: "registry_name", Value: orNil(v.RegistryName)},
		{Key: "registry_scope", Value: orNil(v.RegistryScope)}, {Key: "registry_trust", Value: orNil(v.RegistryTrust)},
		{Key: "removed_upstream", Value: v.RemovedUpstream},
		{Key: "version", Value: orNil(v.Version)}, {Key: "latest_version", Value: orNil(v.LatestVersion)},
		{Key: "agent_count", Value: v.Agents}, {Key: "revision", Value: v.Revision}, {Key: "bundle", Value: orNil(v.Bundle)},
	}
}

func skillMemberJSON(m domain.SkillMember) wirejson.Object {
	deps := make([]any, len(m.Dependencies))
	for i, d := range m.Dependencies {
		deps[i] = d
	}
	return wirejson.Object{{Key: "parent_skill_id", Value: m.ParentSkillID}, {Key: "child_skill_id", Value: m.ChildSkillID},
		{Key: "order", Value: json.Number(strconv.FormatInt(int64(m.Order), 10))}, {Key: "is_required", Value: m.IsRequired},
		{Key: "dependencies", Value: deps}}
}

func (s *Server) skills() *service.Skills { return s.ext.Skills }

func (s *Server) ListSkillsV1SkillsGet(ctx context.Context, _ gen.ListSkillsV1SkillsGetRequestObject) (gen.ListSkillsV1SkillsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	si := areaInput[skillInput](ctx)
	items, total, err := s.skills().List(ctx, c, si.list)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(items))
	for i, v := range items {
		out[i] = skillJSON(v)
	}
	p := si.page
	return ok(wirejson.Object{{Key: "items", Value: out}, {Key: "total", Value: total}, {Key: "page", Value: p.Page},
		{Key: "page_size", Value: p.PageSize}, {Key: "has_next", Value: p.Offset()+p.PageSize < total}}), nil
}

func (s *Server) CreateSkillV1SkillsPost(ctx context.Context, _ gen.CreateSkillV1SkillsPostRequestObject) (gen.CreateSkillV1SkillsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	si := areaInput[skillInput](ctx)
	var v service.SkillView
	if si.content != nil && *si.content != "" {
		v, err = s.skills().CreateFromContent(ctx, c, *si.content, si.name, si.description)
	} else {
		v, err = s.skills().CreateFromGitHub(ctx, c, *si.githubURL, si.name, si.description)
	}
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) UploadSkillV1SkillsUploadPost(ctx context.Context, rq gen.UploadSkillV1SkillsUploadPostRequestObject) (gen.UploadSkillV1SkillsUploadPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	var (
		data     []byte
		filename string
		found    bool
	)
	for {
		part, err := rq.Body.NextPart()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, httpx.HTTPError(http.StatusBadRequest, "There was an error parsing the body")
		}
		if part.FormName() != "file" || found {
			_ = part.Close()
			continue
		}
		found, filename = true, part.FileName()
		data, err = io.ReadAll(io.LimitReader(part, domain.SkillMaxPackageTotalBytes+1))
		_ = part.Close()
		if err != nil {
			return nil, httpx.HTTPError(http.StatusBadRequest, "There was an error parsing the body")
		}
	}
	if !found {
		return nil, httpx.Validation(httpx.Missing("body", "file"))
	}
	if filename == "" || !strings.HasSuffix(strings.ToLower(filename), ".zip") {
		return nil, httpx.HTTPError(http.StatusBadRequest, "File must be a ZIP archive")
	}
	if len(data) > domain.SkillMaxPackageTotalBytes {
		return nil, &domain.SkillValueError{Msg: "Skill package is larger than 50 MB uncompressed"}
	}
	si := areaInput[skillInput](ctx)
	v, err := s.skills().CreateFromZip(ctx, c, data, si.name, si.description)
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) GetSkillV1SkillsSkillIdGet(ctx context.Context, rq gen.GetSkillV1SkillsSkillIdGetRequestObject) (gen.GetSkillV1SkillsSkillIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.skills().Get(ctx, c, uuid.UUID(rq.SkillId))
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) UpdateAllSkillsV1SkillsUpdateAllPost(ctx context.Context, _ gen.UpdateAllSkillsV1SkillsUpdateAllPostRequestObject) (gen.UpdateAllSkillsV1SkillsUpdateAllPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	results, err := s.skills().UpdateAll(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(results))
	for i, r := range results {
		var sk any
		if r.Skill != nil {
			sk = skillJSON(*r.Skill)
		}
		out[i] = wirejson.Object{{Key: "skill_id", Value: r.SkillID}, {Key: "name", Value: r.Name}, {Key: "status", Value: r.Status},
			{Key: "error", Value: orNil(r.Error)}, {Key: "skill", Value: sk}}
	}
	return ok(wirejson.Object{{Key: "results", Value: out}}), nil
}

func (s *Server) UpdateInstalledSkillV1SkillsSkillIdUpdatePost(ctx context.Context, rq gen.UpdateInstalledSkillV1SkillsSkillIdUpdatePostRequestObject) (gen.UpdateInstalledSkillV1SkillsSkillIdUpdatePostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.skills().UpdateInstalled(ctx, c, uuid.UUID(rq.SkillId), areaInput[skillInput](ctx).discard)
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) ListSkillVersionsV1SkillsSkillIdVersionsGet(ctx context.Context, rq gen.ListSkillVersionsV1SkillsSkillIdVersionsGetRequestObject) (gen.ListSkillVersionsV1SkillsSkillIdVersionsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	vs, err := s.skills().Versions(ctx, c, uuid.UUID(rq.SkillId))
	if err != nil {
		return nil, err
	}
	out := make([]any, len(vs))
	for i, v := range vs {
		out[i] = wirejson.Object{{Key: "id", Value: v.ID}, {Key: "digest", Value: orNil(v.Digest)}, {Key: "reason", Value: v.Reason},
			{Key: "catalog_version", Value: orNil(v.CatalogVersion)}, {Key: "created_by", Value: v.CreatedBy},
			{Key: "created_at", Value: skillUTCISO(v.CreatedAt)}, {Key: "current", Value: v.Current}}
	}
	return ok(out), nil
}

func (s *Server) RollbackSkillV1SkillsSkillIdVersionsVersionIdRollbackPost(ctx context.Context, rq gen.RollbackSkillV1SkillsSkillIdVersionsVersionIdRollbackPostRequestObject) (gen.RollbackSkillV1SkillsSkillIdVersionsVersionIdRollbackPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.skills().Rollback(ctx, c, uuid.UUID(rq.SkillId), uuid.UUID(rq.VersionId))
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) InstallSkillV1SkillsSkillIdInstallPost(ctx context.Context, rq gen.InstallSkillV1SkillsSkillIdInstallPostRequestObject) (gen.InstallSkillV1SkillsSkillIdInstallPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.skills().Install(ctx, c, uuid.UUID(rq.SkillId))
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) GetSkillContentV1SkillsSkillIdContentGet(ctx context.Context, rq gen.GetSkillContentV1SkillsSkillIdContentGetRequestObject) (gen.GetSkillContentV1SkillsSkillIdContentGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, text, err := s.skills().Content(ctx, c, uuid.UUID(rq.SkillId))
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "id", Value: v.ID}, {Key: "name", Value: v.Name}, {Key: "content", Value: text}}), nil
}

func (s *Server) ListSkillFilesV1SkillsSkillIdFilesGet(ctx context.Context, rq gen.ListSkillFilesV1SkillsSkillIdFilesGetRequestObject) (gen.ListSkillFilesV1SkillsSkillIdFilesGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id := uuid.UUID(rq.SkillId)
	files, err := s.skills().Files(ctx, c, id, areaInput[skillInput](ctx).includeURLs)
	if err != nil {
		return nil, err
	}
	out := make([]any, len(files))
	for i, f := range files {
		out[i] = wirejson.Object{{Key: "path", Value: f.Path}, {Key: "size", Value: f.Size}, {Key: "url", Value: orNil(f.URL)}}
	}
	return ok(wirejson.Object{{Key: "skill_id", Value: id.String()}, {Key: "files", Value: out}}), nil
}

// skillRedirect is RedirectResponse(url): a 307 with an empty body.
type skillRedirect struct{ url string }

func (x skillRedirect) VisitGetSkillFileV1SkillsSkillIdFilesPathGetResponse(w http.ResponseWriter) error {
	w.Header().Set("Location", x.url)
	w.Header().Set("Content-Length", "0")
	w.WriteHeader(http.StatusTemporaryRedirect)
	return nil
}

func (s *Server) GetSkillFileV1SkillsSkillIdFilesPathGet(ctx context.Context, rq gen.GetSkillFileV1SkillsSkillIdFilesPathGetRequestObject) (gen.GetSkillFileV1SkillsSkillIdFilesPathGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	u, err := s.skills().FileURL(ctx, c, uuid.UUID(rq.SkillId), rq.Path)
	if err != nil {
		return nil, err
	}
	if areaInput[skillInput](ctx).redo {
		return skillRedirect{url: u}, nil
	}
	return ok(wirejson.Object{{Key: "url", Value: u}}), nil
}

func (s *Server) UpdateSkillV1SkillsSkillIdPut(ctx context.Context, rq gen.UpdateSkillV1SkillsSkillIdPutRequestObject) (gen.UpdateSkillV1SkillsSkillIdPutResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	si := areaInput[skillInput](ctx)
	if err := s.skills().RequireUnmanaged(ctx, c.Workspace, uuid.UUID(rq.SkillId)); err != nil {
		return nil, err
	}
	v, err := s.skills().Update(ctx, c, uuid.UUID(rq.SkillId), si.name, si.description, si.content)
	if err != nil {
		return nil, err
	}
	return ok(skillJSON(v)), nil
}

func (s *Server) DeleteSkillV1SkillsSkillIdDelete(ctx context.Context, rq gen.DeleteSkillV1SkillsSkillIdDeleteRequestObject) (gen.DeleteSkillV1SkillsSkillIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	id := uuid.UUID(rq.SkillId)
	if err := s.skills().Delete(ctx, c, id); err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "status", Value: "deleted"}, {Key: "id", Value: id.String()}}), nil
}

func (s *Server) AddSkillMemberV1SkillsSkillIdMembersPost(ctx context.Context, rq gen.AddSkillMemberV1SkillsSkillIdMembersPostRequestObject) (gen.AddSkillMemberV1SkillsSkillIdMembersPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	m := areaInput[skillInput](ctx).member
	m.ParentSkillID = uuid.UUID(rq.SkillId).String()
	m, err = s.skills().AddMember(ctx, c, m)
	if err != nil {
		return nil, err
	}
	return ok(skillMemberJSON(m)), nil
}

func (s *Server) ListSkillMembersV1SkillsSkillIdMembersGet(ctx context.Context, rq gen.ListSkillMembersV1SkillsSkillIdMembersGetRequestObject) (gen.ListSkillMembersV1SkillsSkillIdMembersGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	ms, err := s.skills().Members(ctx, c, uuid.UUID(rq.SkillId))
	if err != nil {
		return nil, err
	}
	out := make([]any, len(ms))
	for i, m := range ms {
		out[i] = skillMemberJSON(m)
	}
	return ok(out), nil
}

func (s *Server) RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDelete(ctx context.Context, rq gen.RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteRequestObject) (gen.RemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	parent, child := uuid.UUID(rq.SkillId), uuid.UUID(rq.ChildSkillId)
	if err := s.skills().RemoveMember(ctx, c, parent, child); err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "status", Value: "removed"}, {Key: "parent_skill_id", Value: parent.String()},
		{Key: "child_skill_id", Value: child.String()}}), nil
}

func (s *Server) FlattenSkillMembersV1SkillsSkillIdFlattenGet(ctx context.Context, rq gen.FlattenSkillMembersV1SkillsSkillIdFlattenGetRequestObject) (gen.FlattenSkillMembersV1SkillsSkillIdFlattenGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	ids, err := s.skills().Flatten(ctx, c, uuid.UUID(rq.SkillId))
	if err != nil {
		return nil, err
	}
	out := make([]any, len(ids))
	for i, id := range ids {
		out[i] = id
	}
	return ok(out), nil
}

func (x response) VisitListSkillsV1SkillsGetResponse(w http.ResponseWriter) error { return x.visit(w) }
func (x response) VisitCreateSkillV1SkillsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateAllSkillsV1SkillsUpdateAllPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUploadSkillV1SkillsUploadPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteSkillV1SkillsSkillIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetSkillV1SkillsSkillIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateSkillV1SkillsSkillIdPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetSkillContentV1SkillsSkillIdContentGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListSkillFilesV1SkillsSkillIdFilesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetSkillFileV1SkillsSkillIdFilesPathGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitFlattenSkillMembersV1SkillsSkillIdFlattenGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitInstallSkillV1SkillsSkillIdInstallPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListSkillMembersV1SkillsSkillIdMembersGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitAddSkillMemberV1SkillsSkillIdMembersPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRemoveSkillMemberV1SkillsSkillIdMembersChildSkillIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateInstalledSkillV1SkillsSkillIdUpdatePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListSkillVersionsV1SkillsSkillIdVersionsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRollbackSkillV1SkillsSkillIdVersionsVersionIdRollbackPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
