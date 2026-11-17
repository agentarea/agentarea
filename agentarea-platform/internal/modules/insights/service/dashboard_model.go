package service

import (
	"encoding/json"
	"errors"
	"math/big"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// Dashboard limits (dashboard.py).
const (
	ScheduleHorizonDays   = 42
	MaxListedRunsPerDay   = 3
	TaskListLimit         = 10
	BlockerListLimit      = 20
	TopAgentsLimit        = 3
	HealthListLimit       = 20
	ProjectionWindowDays  = 7
	DailySpendDays        = 30
	OverviewTaskDays      = 14
	OverviewUpcomingDays  = 7
	OverviewTriggerRuns   = 10
	OverviewPendingLimit  = 20
	ProjectionMethod      = "trailing-7d"
	BookedTaskScanLimit   = 10000
	TitleLength           = 200
	OverviewTitleLength   = 120
	OverviewUnnamedTitle  = "(unnamed task)"
	OverviewInvalidSuffix = " (invalid cron)"
)

// Where each task status shows on the dashboard (_STATUS_PLACE).
func activeStatuses() []string {
	return []string{"submitted", "pending", "preparing", "running", "working", "waiting_for_infrastructure"}
}

func hitlStatuses() []string { return []string{"waiting_for_input", "waiting_for_approval"} }

func continuationStatuses() []string { return []string{"waiting_for_continuation"} }

func blockedStatuses() []string { return []string{"blocked"} }

// finishedStatuses lists a blocked run among the ended ones too.
func finishedStatuses() []string { return []string{"blocked", "completed", "failed", "cancelled"} }

func scheduledStatuses() []string { return []string{"scheduled"} }

// runningStatuses are the active statuses the overview calls running.
func runningStatuses() []string { return []string{"running", "working", "waiting_for_infrastructure"} }

// In reports whether s is one of set.
func In(s string, set []string) bool {
	for _, x := range set {
		if x == s {
			return true
		}
	}
	return false
}

// Cut is s[:n] in characters, as Python slices a str.
func Cut(s string, n int) string {
	if len(s) <= n {
		return s
	}
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func rat(d money.Decimal) *big.Rat {
	r, ok := new(big.Rat).SetString(d.Plain())
	if !ok {
		panic("money: decimal does not read as a rational: " + d.Plain())
	}
	return r
}

// roundHalfEven is r to places decimal places, ROUND_HALF_EVEN, with
// exactly places digits after the point (Decimal.quantize).
func roundHalfEven(r *big.Rat, places int) money.Decimal {
	scale := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(places)), nil)
	x := new(big.Rat).Mul(r, new(big.Rat).SetInt(scale))
	neg := x.Sign() < 0
	x.Abs(x)
	q, rem := new(big.Int).QuoRem(x.Num(), x.Denom(), new(big.Int))
	twice := new(big.Int).Mul(rem, big.NewInt(2))
	if c := twice.Cmp(x.Denom()); c > 0 || (c == 0 && q.Bit(0) == 1) {
		q.Add(q, big.NewInt(1))
	}
	s := q.String()
	if places > 0 {
		for len(s) <= places {
			s = "0" + s
		}
		s = s[:len(s)-places] + "." + s[len(s)-places:]
	}
	if neg && q.Sign() != 0 {
		s = "-" + s
	}
	return money.MustParse(s)
}

// Quantize is d.quantize(Decimal(10) ** -places).
func Quantize(d money.Decimal, places int) money.Decimal { return roundHalfEven(rat(d), places) }

// PctOfCap is round(mtd / cap * 100, 2), nil without a cap or with a zero one.
func PctOfCap(mtd money.Decimal, cap *money.Decimal) *float64 {
	if cap == nil || cap.IsZero() {
		return nil
	}
	r := new(big.Rat).Quo(rat(mtd), rat(*cap))
	r.Mul(r, big.NewRat(100, 1))
	f, err := strconv.ParseFloat(roundHalfEven(r, 2).Plain(), 64)
	if err != nil {
		return nil
	}
	return &f
}

// ProjectMonthEnd is month-to-date spend plus the rest of the month at the
// average of the last ProjectionWindowDays full UTC days (project_month_end);
// today sets no pace.
func ProjectMonthEnd(mtd money.Decimal, byDay map[string]money.Decimal, now time.Time) money.Decimal {
	now = now.UTC()
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	pace := new(big.Rat)
	for i := 1; i <= ProjectionWindowDays; i++ {
		if d, ok := byDay[today.AddDate(0, 0, -i).Format(time.DateOnly)]; ok {
			pace.Add(pace, rat(d))
		}
	}
	pace.Quo(pace, big.NewRat(ProjectionWindowDays, 1))
	next := time.Date(now.Year(), now.Month()+1, 1, 0, 0, 0, 0, time.UTC)
	secs := new(big.Rat).SetFloat64(next.Sub(now).Seconds())
	daysLeft := secs.Quo(secs, big.NewRat(86400, 1))
	total := new(big.Rat).Add(rat(mtd), pace.Mul(pace, daysLeft))
	return roundHalfEven(total, 2)
}

// ErrUnreadableCost is a task result total_cost that is not an amount.
var ErrUnreadableCost = errors.New("total_cost is not a money amount")

// TaskCost reads result.total_cost as JSON text (_task_cost): nil when absent
// or null, ErrUnreadableCost when it is not an amount. A JSON float reads as
// Python's str of it.
func TaskCost(raw string) (*money.Decimal, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" || raw == "null" {
		return nil, nil
	}
	var text string
	switch {
	case strings.HasPrefix(raw, `"`):
		if err := json.Unmarshal([]byte(raw), &text); err != nil {
			return nil, ErrUnreadableCost
		}
	case raw == "true" || raw == "false" || strings.HasPrefix(raw, "{") || strings.HasPrefix(raw, "["):
		return nil, ErrUnreadableCost
	case strings.ContainsAny(raw, ".eE"):
		f, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			return nil, ErrUnreadableCost
		}
		text = wirejson.FormatFloat(f)
	default:
		text = raw
	}
	d, err := money.Parse(text)
	if err != nil {
		return nil, ErrUnreadableCost
	}
	return &d, nil
}

// CurrencySpend is month-to-date spend in a currency no cap counts.
type CurrencySpend struct {
	Currency string
	Amount   money.Decimal
}

// NotCovered is spend_not_covered: nothing without a cap, else the positive
// spend of currencies outside covered, by currency. "" is the billing
// currency of backfilled lines, which caps count.
func NotCovered(byCurrency map[string]money.Decimal, covered map[string]bool) []CurrencySpend {
	if len(covered) == 0 {
		return nil
	}
	var out []CurrencySpend
	for c, a := range byCurrency {
		if c == "" || covered[c] || a.Sign() <= 0 {
			continue
		}
		out = append(out, CurrencySpend{Currency: c, Amount: a})
	}
	sortBy(out, func(a, b CurrencySpend) int { return strings.Compare(a.Currency, b.Currency) })
	return out
}

// SpendCard is the dashboard's spend summary.
type SpendCard struct {
	Today          money.Decimal
	MTD            money.Decimal
	Cap            *money.Decimal
	PctOfCap       *float64
	ProjectedEOM   money.Decimal
	NotCovered     []CurrencySpend
	MTDEstimateUSD money.Decimal
}

// HITLBlocker is a run waiting on a person: an answer, an approval, or to be continued.
type HITLBlocker struct {
	TaskID, AgentID string
	AgentName       *string
	Status          string
	Description     string
	CreatedAt       time.Time
}

// WalletBlocker is an agent whose wallet budget for its period is spent.
type WalletBlocker struct {
	AgentID   string
	AgentName *string
	Budget    money.Decimal
	Period    string
}

// EndedBlocker is a run that failed or was blocked in the last 24 hours.
type EndedBlocker struct {
	TaskID, AgentID string
	AgentName       *string
	Description     string
	Error           *string
	OccurredAt      time.Time
}

// Blockers is everything waiting on someone.
type Blockers struct {
	HITL, AwaitingContinuation []HITLBlocker
	Blocked24h                 []EndedBlocker
	WalletExhausted            []WalletBlocker
	Failed24h                  []EndedBlocker
}

// DashboardTask is a running or recently finished run.
type DashboardTask struct {
	TaskID, AgentID string
	AgentName       *string
	Title           string
	Status          string
	StartedAt       *time.Time
	FinishedAt      *time.Time
	Cost            *money.Decimal
}

// ScheduledRun is a cron firing (TriggerID) or a task booked for later (TaskID).
type ScheduledRun struct {
	FiresAt           time.Time
	TriggerID, TaskID *string
	AgentID           string
	AgentName         *string
	Title             string
}

// FrequentSchedule is a trigger that fires too often to list.
type FrequentSchedule struct {
	TriggerID, AgentID string
	AgentName          *string
	Title              string
	CronExpression     string
	RunsPerDay         int
	NextRunAt          time.Time
}

// Schedule is the weeks ahead.
type Schedule struct {
	HorizonDays int
	Runs        []ScheduledRun
	Frequent    []FrequentSchedule
}

// DaySpend is one UTC day of spend.
type DaySpend struct {
	Date string
	USD  money.Decimal
}

// AgentSpend is an agent's month-to-date spend.
type AgentSpend struct {
	AgentID   string
	AgentName *string
	USD       money.Decimal
}

// RuntimeUsage is what the runtime used this month; quantities, never a price.
type RuntimeUsage struct {
	CPUCoreHours, MemoryGiBHours, StorageGiB money.Decimal
}

// BrokenConnection is an MCP instance whose verification or last call failed.
type BrokenConnection struct {
	InstanceID, Name, Reason string
	Error, At                *string
}

// BrokenTrigger is a trigger that stopped working.
type BrokenTrigger struct {
	TriggerID, Name, AgentID string
	AgentName                *string
	Reason                   string
	ConsecutiveFailures      int
	FailureThreshold         int
	LastExecutionAt          *time.Time
}

// Health is what is broken.
type Health struct {
	Connections []BrokenConnection
	Triggers    []BrokenTrigger
}

// Dashboard is GET /dashboard.
type Dashboard struct {
	Spend       SpendCard
	Blockers    Blockers
	ActiveTasks []DashboardTask
	RecentTasks []DashboardTask
	Schedule    Schedule
	DailySpend  []DaySpend
	TopAgents   []AgentSpend
	Health      Health
	Usage       *RuntimeUsage
}

// ConnectionError is a connection state's error text: a string, or an
// object's message (_connection_error).
func ConnectionError(v any) *string {
	switch e := v.(type) {
	case string:
		return &e
	case map[string]any:
		if m, ok := e["message"].(string); ok {
			return &m
		}
	}
	return nil
}

// DaySeries is n UTC days from start with each day's amount, zero when none.
func DaySeries(start time.Time, n int, byDay map[string]money.Decimal) []DaySpend {
	out := make([]DaySpend, n)
	for i := range n {
		d := start.AddDate(0, 0, i).Format(time.DateOnly)
		amount, ok := byDay[d]
		if !ok {
			amount = money.Zero()
		}
		out[i] = DaySpend{Date: d, USD: amount}
	}
	return out
}
