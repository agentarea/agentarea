package service

import (
	"log/slog"
	"time"
)

// Log is the surface's logger.
func (s *Surface) Log() *slog.Logger { return s.d.Log }

// Now is the surface's clock.
func (s *Surface) Now() time.Time { return s.d.Now() }
