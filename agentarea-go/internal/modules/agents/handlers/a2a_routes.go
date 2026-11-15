package handlers

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// a2aInput is the agent-cards body (AgentCardLookup).
type a2aInput struct{ url string }

func a2aCardBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	s, set := str(o, "url", 0, 0, false, errs)
	if !set {
		*errs = append(*errs, httpx.Missing("body", "url"))
		return
	}
	if s != nil {
		in.area = a2aInput{url: *s}
	}
}

// mountA2A registers the A2A routes: the discovery documents and JSON-RPC
// endpoint under /v1/agents/{agent_id}, which bind the agent's workspace
// themselves, the agent-cards reader under the workspace, and the two routes
// of each agent's own host.
func mountA2A(r chi.Router, on func(rq request) chi.Router, w *gen.ServerInterfaceWrapper, _ Edge, s *Server, errs *httpx.Errors) {
	on(request{body: a2aCardBody}).Post(httpx.WorkspacePrefix+"/a2a/agent-cards", w.ReadAgentCardV1A2aAgentCardsPost)
	h := a2aHandlers{a: s.ext.A2A, errs: errs, maxBody: s.ext.MaxBody}
	p := "/v1/agents/{agent_id}"
	r.Get(p+"/.well-known/agent-card.json", h.card)
	r.Get(p+"/.well-known/a2a-info.json", h.info)
	r.Get(p+"/.well-known/", h.index)
	r.Post(p+"/a2a/rpc", h.rpc)
	r.Get(p+"/a2a/well-known", h.wellKnown)
	r.Post("/", h.hostRPC)
	r.Get("/.well-known/agent-card.json", h.hostCard)
}

func mapA2AError(err error) (*httpx.Error, bool) {
	var (
		forbidden *service.A2AForbiddenError
		missing   *service.A2ACardAgentNotFoundError
		document  *service.A2ADocumentError
		fetch     *service.A2ACardFetchError
	)
	switch {
	case errors.Is(err, service.ErrA2AAgentNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Agent not found"), true
	case errors.Is(err, service.ErrA2AAuthRequired):
		return httpx.HTTPError(http.StatusUnauthorized, "Authentication required").WithHeader("WWW-Authenticate", "Bearer"), true
	case errors.As(err, &forbidden):
		return httpx.HTTPError(http.StatusForbidden, forbidden.Error()), true
	case errors.As(err, &missing):
		return httpx.HTTPError(http.StatusNotFound, missing.Error()), true
	case errors.As(err, &document):
		return httpx.HTTPError(http.StatusInternalServerError, document.Detail).Wrap(err), true
	case errors.As(err, &fetch):
		return httpx.HTTPError(http.StatusBadRequest, fetch.Error()), true
	}
	return nil, false
}

// ReadAgentCardV1A2aAgentCardsPost is POST /a2a/agent-cards.
func (s *Server) ReadAgentCardV1A2aAgentCardsPost(ctx context.Context, _ gen.ReadAgentCardV1A2aAgentCardsPostRequestObject) (gen.ReadAgentCardV1A2aAgentCardsPostResponseObject, error) {
	summary, err := s.ext.A2A.ReadCard(ctx, areaInput[a2aInput](ctx).url)
	if err != nil {
		return nil, err
	}
	return ok(service.A2AToWire(summary)), nil
}

func (x response) VisitReadAgentCardV1A2aAgentCardsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

type a2aHandlers struct {
	a       *service.A2A
	errs    *httpx.Errors
	maxBody int64
}

func (h a2aHandlers) write(w http.ResponseWriter, r *http.Request, body domain.A2AJSON) {
	if err := ok(service.A2AToWire(body)).visit(w); err != nil {
		h.errs.Write(w, r, err)
	}
}

// pathAgent is the agent_id path parameter as FastAPI validates a UUID.
func (h a2aHandlers) pathAgent(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	id, fe := httpx.ValidateUUID(chi.URLParam(r, "agent_id"), "path", "agent_id")
	if fe != nil {
		h.errs.Write(w, r, httpx.Validation(*fe))
		return uuid.UUID{}, false
	}
	return uuid.MustParse(id), true
}

func (h a2aHandlers) document(w http.ResponseWriter, r *http.Request, build func(context.Context, uuid.UUID) (domain.A2AJSON, error)) {
	id, valid := h.pathAgent(w, r)
	if !valid {
		return
	}
	body, err := build(r.Context(), id)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	h.write(w, r, body)
}

func (h a2aHandlers) card(w http.ResponseWriter, r *http.Request) {
	h.document(w, r, func(ctx context.Context, id uuid.UUID) (domain.A2AJSON, error) {
		return h.a.PublicCard(ctx, id, h.a.APIRPCURL(id))
	})
}

func (h a2aHandlers) info(w http.ResponseWriter, r *http.Request)  { h.document(w, r, h.a.Info) }
func (h a2aHandlers) index(w http.ResponseWriter, r *http.Request) { h.document(w, r, h.a.Index) }

func a2aMeta(r *http.Request) service.A2ARequestMeta {
	var meta service.A2ARequestMeta
	if ua := r.Header.Values("User-Agent"); len(ua) > 0 {
		meta.UserAgent = &ua[0]
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		meta.ClientIP = host
	}
	return meta
}

func (h a2aHandlers) admit(w http.ResponseWriter, r *http.Request, rawID string) (service.A2AAdmission, bool) {
	token, _ := authn.BearerToken(r)
	adm, err := h.a.Admit(r.Context(), rawID, token, service.A2APermRead, a2aMeta(r))
	if err != nil {
		h.errs.Write(w, r, err)
		return adm, false
	}
	return adm, true
}

// wellKnown is GET /a2a/well-known: the public card, behind the read check.
func (h a2aHandlers) wellKnown(w http.ResponseWriter, r *http.Request) {
	adm, admitted := h.admit(w, r, chi.URLParam(r, "agent_id"))
	if !admitted {
		return
	}
	id := uuid.MustParse(adm.Agent.ID)
	body, err := h.a.PublicCard(r.Context(), id, h.a.APIRPCURL(id))
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	h.write(w, r, body)
}

func (h a2aHandlers) rpc(w http.ResponseWriter, r *http.Request) {
	h.serveRPC(w, r, chi.URLParam(r, "agent_id"), h.a.APIRPCURL)
}

// serveRPC is the read check, the rate limit, the execute check (the same
// decision) and the dispatcher, in FastAPI's dependency order.
func (h a2aHandlers) serveRPC(w http.ResponseWriter, r *http.Request, rawID string, rpcURL func(uuid.UUID) string) {
	adm, admitted := h.admit(w, r, rawID)
	if !admitted {
		return
	}
	var keyID, userID string
	if p := adm.Principal; p != nil {
		userID = p.UserID
		if p.Credential != nil {
			keyID = p.Credential.KeyID
		}
	}
	if err := h.a.Limit(r.Context(), httpx.A2AIdentity(r, keyID, userID)); err != nil {
		h.errs.Write(w, r, err)
		return
	}
	adm.Auth.Permissions = []string{service.A2APermExecute}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, h.maxBody))
	if tooLarge := (*http.MaxBytesError)(nil); errors.As(err, &tooLarge) {
		err = errors.Join(httpx.ErrBodyTooLarge, err)
	}
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	url := rpcURL(uuid.MustParse(adm.Agent.ID))
	req, failure := h.frame(raw)
	if failure != nil {
		h.write(w, r, failure)
		return
	}
	version := r.Header.Get("A2A-Version")
	if h.a.IsStreaming(req.Method) {
		h.stream(w, r, adm, url, req, version)
		return
	}
	body, err := h.a.Dispatch(r.Context(), adm, url, req, version)
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	h.write(w, r, body)
}

// frame is handle_requests up to the dispatch: the body parsed and framed.
func (h a2aHandlers) frame(raw []byte) (domain.A2ARPCRequest, domain.A2AJSON) {
	decodeErr, utf8 := wirejson.Check(raw)
	if !utf8 {
		return domain.A2ARPCRequest{}, domain.A2ARPCFailure(nil, domain.A2AParseError("The request body is not UTF-8"))
	}
	if decodeErr != nil {
		return domain.A2ARPCRequest{}, domain.A2ARPCFailure(nil, domain.A2AParseError(service.A2AJSONDecodeMessage(raw, decodeErr)))
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return domain.A2ARPCRequest{}, domain.A2ARPCFailure(nil, domain.A2AParseError(err.Error()))
	}
	return domain.A2AFrame(service.A2AFromWire(v))
}

// hostRPC is POST / on an agent's own host; on any other host it is the 405
// the router gives POST / beside GET /.
func (h a2aHandlers) hostRPC(w http.ResponseWriter, r *http.Request) {
	id, isAgent := h.a.HostAgent(r.Host)
	if !isAgent {
		h.errs.Write(w, r, httpx.HTTPError(http.StatusMethodNotAllowed, "").WithHeader("Allow", "GET"))
		return
	}
	h.serveRPC(w, r, id, h.a.HostRPCURL)
}

// hostCard is GET /.well-known/agent-card.json on an agent's own host; on
// any other host the route does not exist.
func (h a2aHandlers) hostCard(w http.ResponseWriter, r *http.Request) {
	id, isAgent := h.a.HostAgent(r.Host)
	if !isAgent {
		h.errs.Write(w, r, httpx.HTTPError(http.StatusNotFound, ""))
		return
	}
	agentID := uuid.MustParse(id)
	body, err := h.a.PublicCard(r.Context(), agentID, h.a.HostRPCURL(agentID))
	if err != nil {
		h.errs.Write(w, r, err)
		return
	}
	h.write(w, r, body)
}
