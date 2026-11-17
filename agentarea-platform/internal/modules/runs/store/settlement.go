package store

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// UnsettledLine is a ledger line waiting on settlement, with its workspace.
type UnsettledLine struct {
	ID           string
	WorkspaceID  string
	CreatedBy    string
	ClientID     string
	SupersedesID string
	Line         domain.CostLine
}

// SettleClaim is when and how many waiting lines a claim takes.
type SettleClaim struct {
	Now         time.Time
	Since       time.Time
	Tick        time.Duration
	MaxInterval time.Duration
	Limit       int32
}

func optText(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// ClaimUnsettled locks the lines of every workspace due for settlement now,
// SKIP LOCKED, inside q's transaction (CrossWorkspaceCostLines.claim_unsettled).
func (Runs) ClaimUnsettled(ctx context.Context, q db.Querier, c SettleClaim) ([]UnsettledLine, error) {
	rows, err := New(q).ClaimUnsettledLines(ctx, ClaimUnsettledLinesParams{
		Since: tstz(c.Since), Now: tstz(c.Now), NowEpoch: float64(c.Now.UnixMicro()) / 1e6,
		TickSeconds: c.Tick.Seconds(), MaxSeconds: c.MaxInterval.Seconds(), Batch: c.Limit,
	})
	if err != nil {
		return nil, err
	}
	out := make([]UnsettledLine, 0, len(rows))
	for _, r := range rows {
		var evidence map[string]any
		dec := json.NewDecoder(strings.NewReader(r.Evidence))
		dec.UseNumber()
		if err := dec.Decode(&evidence); err != nil {
			return nil, fmt.Errorf("line %s evidence: %w", r.ID, err)
		}
		u := UnsettledLine{ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Line: domain.CostLine{
			EventID: r.EventID.String(), Category: r.Category, SubjectType: r.SubjectType,
			Amount: r.Amount, Currency: r.Currency.String, Source: r.Source, Payer: r.Payer, Evidence: evidence,
			Estimate: r.Estimate, OccurredAt: r.OccurredAt.Time.UTC(),
			ProviderCostUSD: optText(r.ProviderCostUsd), VendorCost: optText(r.VendorCost), Quantity: optText(r.Quantity),
		}}
		if r.TaskID.Valid {
			u.Line.TaskID = r.TaskID.UUID.String()
		}
		if r.AgentID.Valid {
			u.Line.AgentID = r.AgentID.UUID.String()
		}
		if r.ClientID.Valid {
			u.ClientID = r.ClientID.UUID.String()
		}
		if r.SupersedesID.Valid {
			u.SupersedesID = r.SupersedesID.UUID.String()
		}
		if r.SubjectID.Valid {
			u.Line.SubjectID = &r.SubjectID.String
		}
		if r.SubjectName.Valid {
			u.Line.SubjectName = &r.SubjectName.String
		}
		if r.CallRef.Valid {
			u.Line.CallRef = &r.CallRef.String
		}
		if r.Unit.Valid {
			u.Line.Unit = &r.Unit.String
		}
		if r.VendorCurrency.Valid {
			u.Line.VendorCurrency = &r.VendorCurrency.String
		}
		out = append(out, u)
	}
	return out, nil
}

// InsertSettledLine records the line that supersedes a waiting one, once per
// (event, category); true when it was new. Its correlation and causation are
// its task's. The write runs in q's transaction, in the line's workspace.
func (Runs) InsertSettledLine(ctx context.Context, q db.Querier, ws scope.Workspace, successor UnsettledLine) (bool, error) {
	l := successor.Line
	eventID, err := parseUUID("event id", l.EventID)
	if err != nil {
		return false, err
	}
	supersedes, err := parseUUID("superseded line id", successor.SupersedesID)
	if err != nil {
		return false, err
	}
	taskID, err := nullUUID(l.TaskID)
	if err != nil {
		return false, err
	}
	agentID, err := nullUUID(l.AgentID)
	if err != nil {
		return false, err
	}
	clientID, err := nullUUID(successor.ClientID)
	if err != nil {
		return false, err
	}
	evidence := l.Evidence
	if evidence == nil {
		evidence = map[string]any{}
	}
	ev, err := json.Marshal(domain.StorableMap(evidence))
	if err != nil {
		return false, err
	}
	n, err := New(q).InsertSettledLine(ctx, InsertSettledLineParams{
		ID: uuid.New(), WorkspaceID: ws.ID(), CreatedBy: successor.CreatedBy, EventID: eventID, Category: l.Category,
		TaskID: taskID, AgentID: agentID, ClientID: clientID, SubjectType: l.SubjectType, SubjectID: textPtr(l.SubjectID),
		SubjectName: textPtr(l.SubjectName), CallRef: textPtr(l.CallRef), Amount: l.Amount, Currency: text(l.Currency),
		ProviderCostUsd: textPtr(l.ProviderCostUSD), Source: l.Source, Evidence: string(ev),
		SupersedesID: uuid.NullUUID{UUID: supersedes, Valid: true}, OccurredAt: tstz(l.OccurredAt), Payer: l.Payer,
		VendorCost: textPtr(l.VendorCost), VendorCurrency: textPtr(l.VendorCurrency), Estimate: l.Estimate,
		Quantity: textPtr(l.Quantity), Unit: textPtr(l.Unit),
	})
	return n > 0, err
}

// DropSuperseded keeps the claimed lines no committed line supersedes yet: a
// worker that committed a successor while this claim waited on its lock
// settled the line already.
func (Runs) DropSuperseded(ctx context.Context, q db.Querier, lines []UnsettledLine) ([]UnsettledLine, error) {
	if len(lines) == 0 {
		return lines, nil
	}
	ids := make([]uuid.UUID, len(lines))
	for i, l := range lines {
		ids[i] = uuid.MustParse(l.ID)
	}
	done, err := New(q).SupersededLines(ctx, ids)
	if err != nil {
		return nil, err
	}
	gone := map[string]bool{}
	for _, id := range done {
		gone[id.String()] = true
	}
	out := lines[:0]
	for _, l := range lines {
		if !gone[l.ID] {
			out = append(out, l)
		}
	}
	return out, nil
}

// ClaimLines claims the lines for token until until; the ids it claimed,
// leaving those another worker holds or that are dead.
func (Runs) ClaimLines(ctx context.Context, q db.Querier, lines []UnsettledLine, token uuid.UUID, now, until time.Time) (map[string]bool, error) {
	ids := make([]uuid.UUID, len(lines))
	for i, l := range lines {
		ids[i] = uuid.MustParse(l.ID)
	}
	got, err := New(q).ClaimLines(ctx, ClaimLinesParams{Ids: ids, ClaimedBy: token, ClaimedUntil: tstz(until), Now: tstz(now)})
	if err != nil {
		return nil, err
	}
	out := make(map[string]bool, len(got))
	for _, id := range got {
		out[id.String()] = true
	}
	return out, nil
}

// ReleaseClaim ends token's claim on the line; it is due again on its schedule.
func (Runs) ReleaseClaim(ctx context.Context, q db.Querier, lineID string, token uuid.UUID) error {
	return New(q).ReleaseClaim(ctx, ReleaseClaimParams{LineID: uuid.MustParse(lineID), ClaimedBy: token})
}

// DeferClaim keeps a line that failed to settle from being claimed for tick
// times two to the power of its earlier failures, at most maxInterval.
func (Runs) DeferClaim(ctx context.Context, q db.Querier, lineID string, token uuid.UUID, now time.Time, tick, maxInterval time.Duration) error {
	return New(q).DeferClaim(ctx, DeferClaimParams{
		Now: tstz(now), TickSeconds: tick.Seconds(), MaxSeconds: maxInterval.Seconds(), LineID: uuid.MustParse(lineID), ClaimedBy: token,
	})
}

// KillClaim marks a line no retry can settle; it is never claimed again.
func (Runs) KillClaim(ctx context.Context, q db.Querier, lineID string, token uuid.UUID, now time.Time, reason string) error {
	return New(q).KillClaim(ctx, KillClaimParams{Now: tstz(now), Reason: text(reason), LineID: uuid.MustParse(lineID), ClaimedBy: token})
}
