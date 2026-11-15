package service

import (
	"context"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

// SpendCapCode is the code a spend cap refusal carries.
const SpendCapCode = "spend_cap_reached"

func monthStart(t time.Time) time.Time {
	t = t.UTC()
	return time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.UTC)
}

func (s *Service) sum(ctx context.Context, tx db.Session, since time.Time, currency string, scope store.SpendScope) (money.Decimal, error) {
	raw, err := s.store.SumSpendSince(ctx, tx, since, currency, scope)
	if err != nil {
		return money.Decimal{}, err
	}
	return money.Parse(raw)
}

type llmCapReached struct {
	spent, cap money.Decimal
	currency   string
	agent      bool
}

// monthlyLLMCapReached is the first monthly cap on LLM spend this month's model lines reached.
func (s *Service) monthlyLLMCapReached(ctx context.Context, tx db.Session, caps []api.SpendCap, agentID, billing string, now time.Time) (*llmCapReached, error) {
	for _, c := range caps {
		if c.Category != "llm" || c.Period == "run" {
			continue
		}
		if c.OwnAgent && agentID == "" {
			continue
		}
		currency := c.Currency
		if currency == "" {
			currency = billing
		}
		scope := store.SpendScope{Category: domain.CostModel}
		if c.OwnAgent {
			scope.AgentID = agentID
		}
		spent, err := s.sum(ctx, tx, monthStart(now), currency, scope)
		if err != nil {
			return nil, err
		}
		if spent.Cmp(c.Amount) >= 0 {
			return &llmCapReached{spent: spent, cap: c.Amount, currency: currency, agent: c.OwnAgent}, nil
		}
	}
	return nil, nil
}

func (r *llmCapReached) message() string {
	scope := "Workspace"
	if r.agent {
		scope = "Agent"
	}
	return fmt.Sprintf("%s monthly LLM spend cap reached (%s %s/%s %s)", scope, r.spent, r.currency, r.cap, r.currency)
}

// SpendCapInput are the caps a run checks: frozen, or the ones set now.
type SpendCapInput struct {
	WorkspaceCap *money.Decimal
	AgentCap     *money.Decimal
	LLMCaps      []api.SpendCap
	CurrentCaps  bool
}

// SpendCapOutput is month-to-date spend against the caps.
type SpendCapOutput struct {
	Exceeded         bool
	MonthToDate      money.Decimal
	Cap              *money.Decimal
	Currency         string
	AgentExceeded    bool
	AgentMonthToDate *money.Decimal
	AgentCap         *money.Decimal
	LLMCapMessage    string
}

// CheckMonthlySpendCap reads month-to-date spend of the workspace and of the agent against their caps.
func (s *Service) CheckMonthlySpendCap(ctx context.Context, p Principal, in SpendCapInput) (SpendCapOutput, error) {
	ws, err := workspace(p)
	if err != nil {
		return SpendCapOutput{}, err
	}
	capWS, capAgent, llm := in.WorkspaceCap, in.AgentCap, in.LLMCaps
	if in.CurrentCaps {
		if s.d.Caps == nil {
			return SpendCapOutput{}, fmt.Errorf("current spend caps were asked for but no caps reader is wired")
		}
		budget, err := s.budget(ctx, p)
		if err != nil {
			return SpendCapOutput{}, err
		}
		capWS, capAgent, llm = nil, nil, nil
		if budget != nil {
			capWS, capAgent = budget.MonthlySpendCap, budget.AgentMonthlySpendCap
			for _, c := range budget.SpendCaps {
				if c.Category == "llm" && c.Period != "run" {
					llm = append(llm, c)
				}
			}
		}
	}
	currency := string(s.d.Pricing.Currency())
	now := s.now()
	out := SpendCapOutput{Cap: capWS, AgentCap: capAgent, Currency: currency}
	err = s.readSession(ctx, ws, func(tx db.Session) error {
		spent, err := s.sum(ctx, tx, monthStart(now), currency, store.SpendScope{})
		if err != nil {
			return err
		}
		out.MonthToDate = spent
		out.Exceeded = capWS != nil && spent.Cmp(*capWS) >= 0
		if capAgent != nil {
			agentSpent, err := s.sum(ctx, tx, monthStart(now), currency, store.SpendScope{AgentID: p.AgentID})
			if err != nil {
				return err
			}
			out.AgentMonthToDate = &agentSpent
			out.AgentExceeded = agentSpent.Cmp(*capAgent) >= 0
		}
		reached, err := s.monthlyLLMCapReached(ctx, tx, llm, p.AgentID, currency, now)
		if err != nil {
			return err
		}
		if reached != nil {
			out.LLMCapMessage = reached.message()
		}
		return nil
	})
	return out, err
}

// DelegatedSpend is what a delegated agent's task has spent, every line of it.
func (s *Service) DelegatedSpend(ctx context.Context, p Principal, taskID string) (money.Decimal, error) {
	ws, err := workspace(p)
	if err != nil {
		return money.Decimal{}, err
	}
	var spent money.Decimal
	err = s.readSession(ctx, ws, func(tx db.Session) error {
		spent, err = s.sum(ctx, tx, time.Unix(0, 0), string(s.d.Pricing.Currency()), store.SpendScope{TaskID: taskID})
		return err
	})
	return spent, err
}

// refuseAtSpendCap raises SpendCapReachedError when a monthly cap a model
// call falls under is reached, with the caps set now (refuse_model_call_at_spend_cap).
func (s *Service) refuseAtSpendCap(ctx context.Context, p Principal, frozen *api.BudgetPolicy) error {
	if s.d.Caps == nil {
		return nil
	}
	live, err := s.budget(ctx, p)
	if err != nil {
		return err
	}
	budget := mergeBudget(live, frozen)
	if budget == nil || (budget.MonthlySpendCap == nil && budget.AgentMonthlySpendCap == nil && !hasLLMCap(budget.SpendCaps)) {
		return nil
	}
	ws, err := workspace(p)
	if err != nil {
		return err
	}
	currency := string(s.d.Pricing.Currency())
	now := s.now()
	return s.readSession(ctx, ws, func(tx db.Session) error {
		if c := budget.MonthlySpendCap; c != nil {
			spent, err := s.sum(ctx, tx, monthStart(now), currency, store.SpendScope{})
			if err != nil {
				return err
			}
			if spent.Cmp(*c) >= 0 {
				return spendCapReached(fmt.Sprintf("Workspace monthly spend cap reached (%s %s/%s %s)", spent, currency, c, currency))
			}
		}
		if c := budget.AgentMonthlySpendCap; c != nil {
			spent, err := s.sum(ctx, tx, monthStart(now), currency, store.SpendScope{AgentID: p.AgentID})
			if err != nil {
				return err
			}
			if spent.Cmp(*c) >= 0 {
				return spendCapReached(fmt.Sprintf("Agent monthly spend cap reached (%s %s/%s %s)", spent, currency, c, currency))
			}
		}
		reached, err := s.monthlyLLMCapReached(ctx, tx, budget.SpendCaps, p.AgentID, currency, now)
		if err != nil {
			return err
		}
		if reached != nil {
			return spendCapReached(reached.message())
		}
		return nil
	})
}

func hasLLMCap(caps []api.SpendCap) bool {
	for _, c := range caps {
		if c.Category == "llm" && c.Period != "run" {
			return true
		}
	}
	return false
}

// mergeBudget is current_budget: the monthly caps set now, the per-run limits frozen in the run.
func mergeBudget(live, frozen *api.BudgetPolicy) *api.BudgetPolicy {
	if live == nil && frozen == nil {
		return nil
	}
	out := &api.BudgetPolicy{}
	if frozen != nil {
		out.RunBudget, out.ServiceBudget = frozen.RunBudget, frozen.ServiceBudget
		for _, c := range frozen.SpendCaps {
			if c.Period == "run" {
				out.SpendCaps = append(out.SpendCaps, c)
			}
		}
	}
	if live != nil {
		out.MonthlySpendCap, out.AgentMonthlySpendCap = live.MonthlySpendCap, live.AgentMonthlySpendCap
		for _, c := range live.SpendCaps {
			if c.Period != "run" {
				out.SpendCaps = append(out.SpendCaps, c)
			}
		}
	}
	return out
}

func spendCapReached(reason string) error {
	return nonRetryable("SpendCapReachedError", reason, nil, map[string]any{"code": SpendCapCode, "reason": reason})
}
