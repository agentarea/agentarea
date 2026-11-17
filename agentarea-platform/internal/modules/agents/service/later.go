package service

// UseModels sets the model instance reads of a module built after agents.
func (s *Service) UseModels(m Models) { s.d.Models = m }

// UseConnections sets the connection binding and loans of a module built after agents.
func (s *Service) UseConnections(c Connections) { s.d.Connections = c }

// UseApprovals sets the approval rules of a module built after agents.
func (s *Service) UseApprovals(a Approvals) { s.d.Approvals = a }
