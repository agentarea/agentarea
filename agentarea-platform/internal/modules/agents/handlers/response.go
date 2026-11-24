package handlers

import (
	"net/http"
	"strconv"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// response is a JSONResponse body as Starlette writes it, or an empty 204.
type response struct {
	status int
	body   any
}

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

func noContent() response  { return response{status: http.StatusNoContent} }
func ok(body any) response { return response{status: http.StatusOK, body: body} }
