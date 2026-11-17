package service

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"testing"
	"time"
)

type collector struct {
	batches [][]map[string]any
	fail    error
}

func (c *collector) Post(_ context.Context, batch []map[string]any) error {
	if c.fail != nil {
		return c.fail
	}
	c.batches = append(c.batches, batch)
	return nil
}

func newSender(c Collector, clock *time.Time, log *bytes.Buffer) *Sender {
	return NewSender("inst", "1.2.3", "oss", c, func() time.Time { return *clock }, slog.New(slog.NewTextHandler(log, nil)))
}

func TestEventsCarryTheContextAndGoInBatches(t *testing.T) {
	c, now, log := &collector{}, time.Date(2026, 11, 17, 10, 0, 0, 0, time.UTC), &bytes.Buffer{}
	s := newSender(c, &now, log)
	for i := range MaxBatch + 1 {
		s.Enqueue(map[string]any{"event": "sign_up", "user_id": fmt.Sprint(i)})
	}
	if sent := s.Flush(context.Background()); sent != MaxBatch+1 || len(c.batches) != 2 || len(c.batches[1]) != 1 {
		t.Fatalf("sent %d in %d batches", sent, len(c.batches))
	}
	e := c.batches[0][0]
	ctx := e["context"].(map[string]any)
	if e["event"] != "sign_up" || e["occurred_at"] != "2026-11-17T10:00:00.000000+00:00" || ctx["install_id"] != "inst" || ctx["edition"] != "oss" {
		t.Fatalf("%v", e)
	}
	if s.Flush(context.Background()) != 0 {
		t.Fatal("the queue was not emptied")
	}
}

func TestCountersRollUpIntoOneEventAndOverflow(t *testing.T) {
	c, now := &collector{}, time.Now()
	s := newSender(c, &now, &bytes.Buffer{})
	s.Count("run_refused", map[string]string{"reason": "no_credits"})
	s.Count("run_refused", map[string]string{"reason": "no_credits"})
	for i := range MaxCounterSeries + 2 {
		s.Count("connector_check", map[string]string{"outcome": fmt.Sprint(i)})
	}
	s.SendAll(context.Background())
	counters := c.batches[0][0]["properties"].(map[string]any)["counters"].([]map[string]any)
	if len(counters) != MaxCounterSeries+1 || counters[0]["count"] != 2 || counters[0]["name"] != "run_refused" {
		t.Fatalf("%d %v", len(counters), counters[0])
	}
	last := counters[len(counters)-1]
	if last["labels"].(map[string]string)["overflow"] != "true" || last["count"] != 3 {
		t.Fatalf("%v", last)
	}
	s.SendAll(context.Background())
	if len(c.batches) != 1 {
		t.Fatal("an empty roll-up was sent")
	}
}

func TestQueueKeepsTheNewest(t *testing.T) {
	c, now := &collector{}, time.Now()
	s := newSender(c, &now, &bytes.Buffer{})
	for i := range MaxQueued + 5 {
		s.Enqueue(map[string]any{"event": fmt.Sprint(i)})
	}
	s.Flush(context.Background())
	var all []map[string]any
	for _, b := range c.batches {
		all = append(all, b...)
	}
	if len(all) != MaxQueued || all[0]["event"] != "5" {
		t.Fatalf("%d %v", len(all), all[0]["event"])
	}
}

func TestAnOutageIsLoggedOnceADayAndOnRecovery(t *testing.T) {
	c, now, log := &collector{fail: errors.New("503")}, time.Now(), &bytes.Buffer{}
	s := newSender(c, &now, log)
	send := func() {
		s.Enqueue(map[string]any{"event": "x"})
		s.Flush(context.Background())
	}
	send()
	now = now.Add(time.Hour)
	send()
	if n := strings.Count(log.String(), "level=WARN"); n != 1 {
		t.Fatalf("%d warnings: %s", n, log)
	}
	now = now.Add(24 * time.Hour)
	send()
	if !strings.Contains(log.String(), "still not accepting events") || !strings.Contains(log.String(), "dropped=2") {
		t.Fatal(log.String())
	}
	c.fail = nil
	send()
	if !strings.Contains(log.String(), "accepts events again") || !strings.Contains(log.String(), "dropped=3") {
		t.Fatal(log.String())
	}
}
