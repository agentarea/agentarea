package handlers

import (
	"context"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// sseFrame is one JSON-RPC response as EventSourceResponse writes it.
func sseFrame(body domain.A2AJSON, failed bool) ([]byte, error) {
	data, err := wirejson.Marshal(service.A2AToWire(body), wirejson.Dumps)
	if err != nil {
		return nil, err
	}
	out := make([]byte, 0, len(data)+24)
	if failed {
		out = append(out, "event: error\r\n"...)
	}
	out = append(out, "data: "...)
	out = append(out, data...)
	return append(out, "\r\n\r\n"...), nil
}

type a2aStreamResult struct {
	body domain.A2AJSON
	err  error
}

// stream serves SendStreamingMessage and SubscribeToTask: an error before the
// first event answers as plain JSON, the rest is an event stream.
func (h a2aHandlers) stream(w http.ResponseWriter, r *http.Request, adm service.A2AAdmission, rpcURL string, req domain.A2ARPCRequest, version string) {
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	frames := make(chan []byte)
	done := make(chan a2aStreamResult, 1)
	go func() {
		body, err := h.a.DispatchStream(ctx, adm, rpcURL, req, version, func(b domain.A2AJSON, failed bool) error {
			frame, err := sseFrame(b, failed)
			if err != nil {
				return err
			}
			select {
			case frames <- frame:
				return nil
			case <-ctx.Done():
				return ctx.Err()
			}
		})
		done <- a2aStreamResult{body: body, err: err}
		close(frames)
	}()
	first, open := <-frames
	if !open {
		res := <-done
		switch {
		case res.err != nil:
			h.errs.Write(w, r, res.err)
		case res.body != nil:
			h.write(w, r, res.body)
		default:
			if _, err := httpx.StartSSE(w, r); err != nil {
				h.errs.Write(w, r, err)
			}
		}
		return
	}
	sse, err := httpx.StartSSE(w, r)
	if err != nil {
		cancel()
		<-done
		return
	}
	if err := sse.Write(first); err == nil {
		_ = sse.Pump(ctx, frames, httpx.SSEHeartbeat)
	}
	cancel()
	<-done
}
