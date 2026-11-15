package contract_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"regexp"
	"slices"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/app"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/workflows"
)

// entry is one Python entry of a manifest; Source is "path:line" under agentarea-platform/.
type entry struct {
	Name     string `json:"name"`
	Kind     string `json:"kind"`
	Source   string `json:"source"`
	Queue    string `json:"queue,omitempty"`
	Process  string `json:"process,omitempty"`
	Program  string `json:"program,omitempty"`
	LiveOnly *bool  `json:"live_only,omitempty"`
}

type manifest struct {
	ExtractedFrom string  `json:"extracted_from"`
	Entries       []entry `json:"entries"`
	Dead          []entry `json:"dead,omitempty"`
}

func loadManifest(t *testing.T, kind string, kinds ...string) manifest {
	t.Helper()
	data, err := os.ReadFile(kind + ".json")
	if err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	var m manifest
	if err := dec.Decode(&m); err != nil {
		t.Fatalf("%s.json: %v", kind, err)
	}
	source := regexp.MustCompile(`^(apps|libs)/[\w./-]+\.py:\d+$`)
	seen := map[string]bool{}
	for _, e := range append(slices.Clone(m.Entries), m.Dead...) {
		if seen[e.Name] {
			t.Errorf("%s.json: %s listed twice", kind, e.Name)
		}
		seen[e.Name] = true
		if !source.MatchString(e.Source) {
			t.Errorf("%s.json: %s: source %q is not path:line", kind, e.Name, e.Source)
		}
		if !slices.Contains(kinds, e.Kind) {
			t.Errorf("%s.json: %s: kind %q, want one of %v", kind, e.Name, e.Kind, kinds)
		}
	}
	return m
}

// lines are the non-comment lines of file, split once at sep.
func lines(t *testing.T, file, sep string) map[string]string {
	t.Helper()
	data, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, val, ok := strings.Cut(line, sep)
		key, val = strings.TrimSpace(key), strings.TrimSpace(val)
		if !ok || key == "" || val == "" {
			t.Errorf("%s: %q is not \"<name>%s<text>\"", file, line, sep)
			continue
		}
		if _, dup := out[key]; dup {
			t.Errorf("%s: %s listed twice", file, key)
		}
		out[key] = val
	}
	return out
}

// ratchet fails on an entry Go lacks that <kind>-pending.txt and
// <kind>-dropped.txt do not list, on one Go has that either still lists, and
// on a line naming no entry.
func ratchet(t *testing.T, kind string, m manifest, have func(entry) bool) {
	t.Helper()
	pending := lines(t, kind+"-pending.txt", " -- ")
	dropped := lines(t, kind+"-dropped.txt", " -- ")
	names := map[string]bool{}
	ported := 0
	for _, e := range m.Entries {
		names[e.Name] = true
		inGo, isPending, isDropped := have(e), pending[e.Name] != "", dropped[e.Name] != ""
		switch {
		case inGo && isPending:
			t.Errorf("%s: Go has it now; remove it from %s-pending.txt", e.Name, kind)
		case inGo && isDropped:
			t.Errorf("%s: Go has it; remove it from %s-dropped.txt", e.Name, kind)
		case isPending && isDropped:
			t.Errorf("%s: in both %s-pending.txt and %s-dropped.txt", e.Name, kind, kind)
		case !inGo && !isPending && !isDropped:
			t.Errorf("%s (%s): Go lacks it; port it or list it in %s-pending.txt", e.Name, e.Source, kind)
		case inGo:
			ported++
		}
	}
	for file, list := range map[string]map[string]string{kind + "-pending.txt": pending, kind + "-dropped.txt": dropped} {
		for name := range list {
			if !names[name] {
				t.Errorf("%s: %s is not in %s.json", file, name, kind)
			}
		}
	}
	t.Logf("%s: %d entries, %d ported, %d pending, %d dropped", kind, len(m.Entries), ported, len(pending), len(dropped))
}

// goMapping reads <kind>-go.txt: every Go name, with the Python entries it
// does the work of, "- reason" for none, or "? reason" for one no role
// starts yet. It fails on a Go name the file misses or that Go no longer has.
func goMapping(t *testing.T, kind string, m manifest, goNames map[string]bool, unwiredAllowed bool) map[string]bool {
	t.Helper()
	file := kind + "-go.txt"
	mapping := lines(t, file, " = ")
	names := map[string]bool{}
	for _, e := range m.Entries {
		names[e.Name] = true
	}
	ported := map[string]bool{}
	for g, val := range mapping {
		if !goNames[g] {
			t.Errorf("%s: Go has no %q", file, g)
		}
		switch {
		case strings.HasPrefix(val, "- "):
		case strings.HasPrefix(val, "? ") && unwiredAllowed:
		default:
			for _, p := range strings.Split(val, ",") {
				p = strings.TrimSpace(p)
				if !names[p] {
					t.Errorf("%s: %s maps to %q, which is not in %s.json", file, g, p, kind)
				}
				ported[p] = true
			}
		}
	}
	for g := range goNames {
		if _, ok := mapping[g]; !ok {
			t.Errorf("Go has %q; say in %s which Python %s it ports, or \"- reason\"", g, file, kind)
		}
	}
	return ported
}

func TestTemporalManifest(t *testing.T) {
	m := loadManifest(t, "temporal", "workflow", "activity")
	queues := map[string]string{}
	for _, w := range workflows.AgentQueueWorkflows() {
		queues[w.Name] = "agent"
	}
	for _, w := range workflows.TriggerQueueWorkflows() {
		queues[w.Name] = "trigger"
	}
	activities := map[string]bool{}
	for _, s := range workflows.ActivitySpecs() {
		activities[s.Name] = true
	}
	for _, e := range m.Dead {
		if activities[e.Name] || queues[e.Name] != "" {
			t.Errorf("%s is dead in Python (registered, never scheduled) and Go registers it", e.Name)
		}
	}
	ratchet(t, "temporal", m, func(e entry) bool {
		if e.Kind == "activity" {
			return activities[e.Name]
		}
		q, ok := queues[e.Name]
		if ok && q != e.Queue {
			t.Errorf("workflow %s: Go registers it on the %s queue, Python on %s", e.Name, q, e.Queue)
		}
		return ok
	})
}

func TestEventsManifest(t *testing.T) {
	m := loadManifest(t, "events", "task_event", "domain_event")
	published := scanGo(t).envelopes
	ratchet(t, "events", m, func(e entry) bool {
		if e.Kind == "domain_event" {
			return published[e.Name]
		}
		if !domain.KnownEventType(e.Name) {
			return false
		}
		if e.LiveOnly == nil || domain.LiveOnly(e.Name) != *e.LiveOnly {
			t.Errorf("task event %s: live only in Go %v, in Python %v", e.Name, domain.LiveOnly(e.Name), e.LiveOnly != nil && *e.LiveOnly)
		}
		return true
	})
}

func TestLoopsManifest(t *testing.T) {
	m := loadManifest(t, "loops", "consumer", "periodic", "schedule", "temporal_worker", "listener", "metrics")
	ported := goMapping(t, "loops", m, scanGo(t).components, true)
	ratchet(t, "loops", m, func(e entry) bool { return ported[e.Name] })
}

func TestCLIManifest(t *testing.T) {
	m := loadManifest(t, "cli", "command", "module_main")
	subcommands := map[string]bool{}
	for _, s := range app.Subcommands() {
		subcommands[s] = true
	}
	ported := goMapping(t, "cli", m, subcommands, false)
	ratchet(t, "cli", m, func(e entry) bool { return ported[e.Name] })
}
