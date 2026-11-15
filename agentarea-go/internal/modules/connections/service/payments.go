package service

import (
	"crypto/rand"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/payment"
	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

// UseWallets sets the agents' wallets a call's 402 is paid from; wallet is
// built after connections.
func (s *Service) UseWallets(w walletapi.Wallets) { s.d.Wallets = w }

// paying is the payment side of a run's call: nil, paying nothing, without
// wallets, an agent or a call ref.
func (s *Service) paying(ws scope.Workspace, userID, agentID, toolName, toolCallID string, paid api.PaidCall) *payment.Session {
	if s.d.Wallets == nil || s.d.Out == nil || agentID == "" || paid.CallRef == "" {
		return nil
	}
	return payment.NewSession(s.d.Wallets, payment.Protocols{RPC: s.d.Out.Transport(netguard.Member), Now: s.d.Now, Rand: rand.Reader},
		payment.Call{Workspace: ws, UserID: userID, AgentID: agentID, ExecutionID: paid.ExecutionID, CallRef: paid.CallRef,
			ToolName: toolName, ToolCallID: toolCallID}, s.d.Log)
}
