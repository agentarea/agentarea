package streams

import "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"

// LiveNotices is the live event notices hub the events page's stream reads; a process that
// serves it runs it.
func (m *Module) LiveNotices() lifecycle.Component {
	return lifecycle.Loop("live event notices hub", m.svc.RunLiveNotices)
}
