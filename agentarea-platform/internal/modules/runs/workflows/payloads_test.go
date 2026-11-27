package workflows

import (
	"bytes"
	"encoding/json"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/service"
)

var (
	decimalType  = reflect.TypeFor[money.Decimal]()
	timeType     = reflect.TypeFor[time.Time]()
	durationType = reflect.TypeFor[time.Duration]()
	snakeCase    = regexp.MustCompile(`^[a-z][a-z0-9]*(_[a-z0-9]+)*$`)
)

// fill sets every field of v to a value that is not its zero value.
func fill(t *testing.T, v reflect.Value, path string) {
	t.Helper()
	switch v.Type() {
	case decimalType:
		v.Set(reflect.ValueOf(money.MustParse("1.250")))
		return
	case timeType:
		v.Set(reflect.ValueOf(time.Date(2026, 11, 12, 10, 0, 0, 123456000, time.UTC)))
		return
	case durationType:
		v.SetInt(int64(90*time.Second + 500*time.Millisecond))
		return
	}
	//exhaustive:ignore
	switch v.Kind() {
	case reflect.String:
		v.SetString("s-" + path)
	case reflect.Bool:
		v.SetBool(true)
	case reflect.Int, reflect.Int64:
		v.SetInt(7)
	case reflect.Float64:
		v.SetFloat(0.5)
	case reflect.Pointer:
		p := reflect.New(v.Type().Elem())
		fill(t, p.Elem(), path)
		v.Set(p)
	case reflect.Slice:
		s := reflect.MakeSlice(v.Type(), 1, 1)
		fill(t, s.Index(0), path+"[]")
		v.Set(s)
	case reflect.Map:
		m := reflect.MakeMap(v.Type())
		e := reflect.New(v.Type().Elem()).Elem()
		fill(t, e, path+"{}")
		m.SetMapIndex(reflect.ValueOf("k"), e)
		v.Set(m)
	case reflect.Interface:
		v.Set(reflect.ValueOf("any-" + path))
	case reflect.Struct:
		for i := range v.NumField() {
			f := v.Type().Field(i)
			tag, _, _ := strings.Cut(f.Tag.Get("json"), ",")
			if !snakeCase.MatchString(tag) {
				t.Errorf("%s.%s: json name %q is not snake_case", path, f.Name, tag)
			}
			fill(t, v.Field(i), path+"."+tag)
		}
	default:
		t.Fatalf("%s: no filler for %s", path, v.Type())
	}
}

func roundTrip(t *testing.T, zero any) {
	t.Helper()
	typ := reflect.TypeOf(zero)
	v := reflect.New(typ)
	fill(t, v.Elem(), typ.Name())
	first, err := json.Marshal(v.Interface())
	if err != nil {
		t.Fatalf("%s: marshal: %v", typ, err)
	}
	back := reflect.New(typ)
	if err := json.Unmarshal(first, back.Interface()); err != nil {
		t.Fatalf("%s: unmarshal: %v", typ, err)
	}
	second, err := json.Marshal(back.Interface())
	if err != nil {
		t.Fatalf("%s: marshal again: %v", typ, err)
	}
	if !bytes.Equal(first, second) {
		t.Errorf("%s does not round-trip:\n%s\n%s", typ, first, second)
	}
	if bytes.Contains(first, []byte("null")) {
		t.Errorf("%s: a filled field was written as null: %s", typ, first)
	}
}

func TestPayloadsRoundTrip(t *testing.T) {
	extra := []any{RunnerTurnUpdate{}}
	for _, s := range ActivitySpecs() {
		for _, p := range []any{s.In, s.Out} {
			if p != nil {
				roundTrip(t, p)
			}
		}
	}
	for _, p := range extra {
		roundTrip(t, p)
	}
}

func TestActivitySpecs(t *testing.T) {
	names := []string{
		api.ActivityResolveRunConfig, api.ActivityCheckMonthlySpendCap, api.ActivityRecord,
		api.ActivityUpdateGovernanceSnapshot, api.ActivityCreateDelegationTask, api.ActivityDelegatedTaskSpend,
		api.ActivityCallLLM, api.ActivityCompactMessages, api.ActivityExecuteTool, api.ActivityGetRemoteTask,
		api.ActivityCancelRemoteTask, api.ActivityValidateArtifacts,
		api.ActivityActivateSkill, api.ActivityRecallHistory, api.ActivityStoreContextOutput,
		api.ActivitySearchHistory, api.ActivityRunRunnerTurn,
		api.ActivityDeliverToRunner, api.ActivityStartUndispatchedTasks, api.ActivitySyncCronSchedules,
		api.ActivityEvaluateTriggerConditions, api.ActivityExecuteTrigger, api.ActivityRecordTriggerExecution,
		api.ActivityFireTriggerBatch, api.ActivityCloseTriggerBatch,
	}
	kinds := Kinds()
	if len(kinds) != len(ActivitySpecs()) {
		t.Errorf("duplicate activity names: %d specs, %d names", len(ActivitySpecs()), len(kinds))
	}
	if len(kinds) != len(names) {
		t.Errorf("%d specs for %d names", len(kinds), len(names))
	}
	for _, n := range names {
		if !kinds[n].Valid() {
			t.Errorf("%s has no spec or no kind", n)
		}
	}
	step := 0
	for _, s := range ActivitySpecs() {
		if s.StartToClose <= 0 || s.Step < step || s.Queue == "" {
			t.Errorf("%s: start-to-close %s, step %d after %d, queue %q", s.Name, s.StartToClose, s.Step, step, s.Queue)
		}
		if s.Retry.MaxAttempts == 0 && s.ScheduleToClose == 0 && !s.OutageWindow && !s.Unbounded {
			t.Errorf("%s retries forever with no schedule-to-close", s.Name)
		}
		step = s.Step
	}
}

func TestAHeldModelLineCarriesItsVendorCurrency(t *testing.T) {
	usage := usageOf(modelsapi.Usage{Prompt: 1}, &service.ChargeLine{
		ModelInstanceID: "m", Amount: money.MustParse("1.5"), Currency: "EUR", VendorCost: money.MustParse("0.01"),
		VendorCurrency: "USD", Estimate: true, Settle: "capture", HoldID: "h1", PlatformFunded: true,
	})
	raw, err := json.Marshal(map[string]any{"usage": usage})
	if err != nil {
		t.Fatal(err)
	}
	var wrapped map[string]any
	if err := json.Unmarshal(raw, &wrapped); err != nil {
		t.Fatal(err)
	}
	lines := domain.CostLines(domain.StoredEvent{ID: "e1", Type: domain.EventLLMCompleted, Data: map[string]any{
		"task_id": "0b6e7d5c-1d2a-4c3b-9e8f-7a6b5c4d3e2f", "model_id": "m", "managed_by": domain.ManagedByPlatform, "usage": wrapped,
	}}, "EUR")
	if len(lines) != 1 || lines[0].VendorCurrency == nil || *lines[0].VendorCurrency != "USD" {
		t.Fatalf("the settlement would capture without a vendor currency: %+v", lines)
	}
}
