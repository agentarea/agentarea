package catalog

import (
	"errors"
	"log/slog"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

// BundleDeps are the owners a bundle deploy writes through.
type BundleDeps = service.BundleDeps

// UseBundles mounts bundle analyze and install over the owners in d; without
// every owner the routes are not mounted.
func (m *Module) UseBundles(d BundleDeps) {
	if d.DB == nil {
		d.DB = m.d.DB
	}
	d.Guard, d.Net, d.Log, d.Now = m.d.Guard, m.d.Net, m.d.Log, m.d.Now
	if d.Admin == nil {
		d.Admin = m.d.Admin
	}
	b, err := service.NewBundles(d)
	if err != nil {
		var missing *service.MissingDepsError
		if !errors.As(err, &missing) {
			m.bundlesErr = err
			return
		}
		log := m.d.Log
		if log == nil {
			log = slog.Default()
		}
		log.Warn("Bundle routes are not mounted", "missing", strings.Join(missing.Missing, ", "))
		return
	}
	m.bundles = b
}
