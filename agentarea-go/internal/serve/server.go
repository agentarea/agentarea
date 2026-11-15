package serve

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"sync"
	"time"
)

// Server is the serve role's listener, a lifecycle.Component and Failer.
type Server struct {
	cfg    Config
	log    *slog.Logger
	srv    *http.Server
	cancel context.CancelFunc
	failed chan error

	mu   sync.Mutex
	addr net.Addr
}

// New builds the listener over the assembled edge.
func New(cfg Config, opts Options, log *slog.Logger, modules ...Module) (*Server, error) {
	a, err := Assemble(cfg, opts, log, modules...)
	if err != nil {
		return nil, fmt.Errorf("routes: %w", err)
	}
	base, cancel := context.WithCancel(context.Background())
	return &Server{
		cfg:    cfg,
		log:    log,
		cancel: cancel,
		failed: make(chan error, 1),
		srv: &http.Server{
			Addr:              cfg.Addr,
			Handler:           a.Handler,
			ReadHeaderTimeout: 10 * time.Second,
			IdleTimeout:       120 * time.Second,
			ErrorLog:          slog.NewLogLogger(log.Handler(), slog.LevelWarn),
			BaseContext:       func(net.Listener) context.Context { return base },
		},
	}, nil
}

// Name implements lifecycle.Component.
func (s *Server) Name() string { return "serve" }

// Addr is the bound address once started.
func (s *Server) Addr() net.Addr {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.addr
}

// Failed implements lifecycle.Failer.
func (s *Server) Failed() <-chan error { return s.failed }

// Start binds the listener and serves in the background.
func (s *Server) Start(ctx context.Context) error {
	ln, err := (&net.ListenConfig{}).Listen(ctx, "tcp", s.cfg.Addr)
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.addr = ln.Addr()
	s.mu.Unlock()
	s.log.InfoContext(ctx, "serving", "addr", ln.Addr().String())
	go func() {
		if err := s.srv.Serve(ln); !errors.Is(err, http.ErrServerClosed) {
			s.failed <- err
		}
	}()
	return nil
}

// Stop lets in-flight requests finish until ctx ends, then closes what is
// left: open event streams never finish on their own, and hijacked
// connections (the runner WebSocket) are not tracked by Shutdown; their
// request contexts end with the base context.
func (s *Server) Stop(ctx context.Context) error {
	defer s.cancel()
	err := s.srv.Shutdown(ctx)
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		s.log.WarnContext(ctx, "shutdown deadline reached; closing open connections")
		return s.srv.Close()
	}
	return err
}
