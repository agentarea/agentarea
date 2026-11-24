package service

import (
	"log/slog"
	"time"
)

// Service is the catalog's use cases.
type Service struct {
	d Deps
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Service{d: d}
}

// Specs is what models reads and writes of provider and model specs.
func (s *Service) Specs() Specs { return Specs{s: s} }

// UseModels wires models' SpecUse once both modules exist.
func (s *Service) UseModels(u SpecUse) { s.d.SpecUse = u }

// HasSpecUse reports whether the provider-spec lists can answer.
func (s *Service) HasSpecUse() bool { return s.d.SpecUse != nil }

// HasSecrets reports whether workspace-registry writes can check credentials.
func (s *Service) HasSecrets() bool { return s.d.Secrets != nil }

// Installs is what agents reads and writes of the catalog to install its agents and skills.
func (s *Service) Installs() Installs { return Installs{DB: s.d.DB, Fetch: s.d.Fetch} }
