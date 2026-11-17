// Package handlers of governance: HTTP handlers, one file per Python router file; server.go maps typed errors to problems.
package handlers

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"time"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/governance"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/service"
)

// Server implements the governance routes (api/v1/policies.py, governance.py,
// audit.py, workspace_secrets.py, egress_exits.py).
type Server struct {
	svc   *service.Service
	admin func(ctx context.Context) error
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server; admin refuses a caller who does not administer the
// workspace (assert_workspace_admin).
func New(svc *service.Service, admin func(ctx context.Context) error) *Server {
	return &Server{svc: svc, admin: admin}
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// EgressDetail is EgressExitsNotSupportedError's message.
const EgressDetail = api.EgressExitsUnsupported

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var (
		nameErr  *secrets.NameError
		notFound *secrets.NotFoundError
		managed  *secrets.ManagedError
		dup      *secrets.DuplicateNameError
		inUse    *secrets.InUseError
		hidden   *service.HiddenSecretError
		exitNF   *api.EgressExitNotFoundError
		exitBad  *service.EgressExitInvalidError
		exitDeny *service.EgressExitForbiddenError
		exitUsed *service.EgressExitInUseError
	)
	switch {
	case errors.Is(err, api.ErrEgressExitsUnsupported):
		return httpx.HTTPError(http.StatusNotFound, EgressDetail), true
	case errors.As(err, &exitNF):
		return httpx.HTTPError(http.StatusNotFound, exitNF.Error()), true
	case errors.As(err, &exitBad):
		return httpx.HTTPError(http.StatusBadRequest, exitBad.Error()), true
	case errors.As(err, &exitDeny):
		return httpx.HTTPError(http.StatusForbidden, exitDeny.Error()), true
	case errors.As(err, &exitUsed):
		return httpx.HTTPError(http.StatusConflict, exitUsed.Error()), true
	case errors.Is(err, authz.ErrDenied):
		return httpx.HTTPError(http.StatusForbidden, "Permission denied"), true
	case errors.Is(err, service.ErrRuleNotFound), errors.Is(err, service.ErrSnapshotNotFound):
		return httpx.HTTPError(http.StatusNotFound, err.Error()), true
	case errors.Is(err, domain.ErrNotEnforceable), errors.Is(err, api.ErrPolicyRefused):
		return httpx.HTTPError(http.StatusUnprocessableEntity, err.Error()), true
	case errors.As(err, &hidden):
		return httpx.HTTPError(http.StatusNotFound, hidden.Error()), true
	case errors.As(err, &notFound):
		return httpx.HTTPError(http.StatusNotFound, notFound.Error()), true
	case errors.As(err, &managed):
		return httpx.HTTPError(http.StatusForbidden, managed.Error()), true
	case errors.As(err, &nameErr):
		return httpx.HTTPError(http.StatusUnprocessableEntity, nameErr.Error()), true
	case errors.As(err, &dup):
		return httpx.HTTPError(http.StatusConflict, dup.Error()), true
	case errors.As(err, &inUse):
		return httpx.HTTPError(http.StatusConflict, inUseDetail(inUse)), true
	}
	return nil, false
}

// inUseDetail is str() of the dict detail delete_secret raises.
func inUseDetail(e *secrets.InUseError) string {
	used := make([]any, len(e.Consumers))
	for i, c := range e.Consumers {
		used[i] = wirejson.Object{
			{Key: "consumer_type", Value: c.ConsumerType},
			{Key: "consumer_id", Value: c.ConsumerID},
			{Key: "field", Value: c.Field},
		}
	}
	return api.PyRepr(wirejson.Object{{Key: "message", Value: e.Error()}, {Key: "used_by", Value: used}})
}

// utcISO is utc_isoformat: a naive value read as UTC, microseconds only when set.
func utcISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "Z"
}

// response is a JSONResponse body as Starlette writes it, or an empty 204.
type response struct {
	status int
	body   any
}

func ok(body any) response      { return response{status: http.StatusOK, body: body} }
func created(body any) response { return response{status: http.StatusCreated, body: body} }
func noContent() response       { return response{status: http.StatusNoContent} }

func (x response) visit(w http.ResponseWriter) error {
	if x.status == http.StatusNoContent {
		w.WriteHeader(x.status)
		return nil
	}
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func (x response) VisitCreateEgressExitV1EgressExitsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreatePolicyRuleV1PoliciesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateSecretV1SecretsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteEgressExitV1EgressExitsExitIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeletePolicyRuleV1PoliciesRuleIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteSecretV1SecretsSecretIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetEgressExitV1EgressExitsExitIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetPolicyRuleV1PoliciesRuleIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetSecretV1SecretsSecretIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetTaskPolicySnapshotV1GovernanceTaskPolicySnapshotsTaskIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListAuditLogsV1AuditLogsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListEgressExitsV1EgressExitsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListPolicyRulesV1PoliciesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListSecretsV1SecretsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRotateSecretV1SecretsSecretIdValuePutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateEgressExitV1EgressExitsExitIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdatePolicyRuleV1PoliciesRuleIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateSecretDescriptionV1SecretsSecretIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
