package service

import (
	"errors"
	"strconv"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// LoadRunSettings reads the run settings of AppSettings:
// AGENTAREA_TASK_OUTAGE_RETRY_WINDOW, AGENTAREA_TASK_OUTAGE_WAIT_BACKOFF
// (durations separated by commas, the last repeats),
// AGENTAREA_TASK_OUTAGE_WAIT_DEADLINE and AGENTAREA_TASK_SKILLS_WINDOW_SHARE (0 < share <= 1).
func LoadRunSettings(l *config.Loader) RunSettings {
	s := RunSettings{
		OutageWait: api.OutageWait{
			RetryWindow: l.DurationEnv("AGENTAREA_TASK_OUTAGE_RETRY_WINDOW", 5*time.Minute),
			Deadline:    l.DurationEnv("AGENTAREA_TASK_OUTAGE_WAIT_DEADLINE", 24*time.Hour),
		},
		SkillsWindowShare: 0.3,
	}
	for _, part := range l.ListEnv("AGENTAREA_TASK_OUTAGE_WAIT_BACKOFF", []string{"1m", "5m", "10m"}) {
		d, err := config.ParseDuration(part)
		if err != nil || d <= 0 {
			l.Fail("AGENTAREA_TASK_OUTAGE_WAIT_BACKOFF", errors.Join(errors.New("each step must be a positive duration"), err))
			continue
		}
		s.OutageWait.Backoff = append(s.OutageWait.Backoff, d)
	}
	if len(s.OutageWait.Backoff) == 0 {
		l.Fail("AGENTAREA_TASK_OUTAGE_WAIT_BACKOFF", errors.New("needs at least one step"))
	}
	if s.OutageWait.RetryWindow <= 0 {
		l.Fail("AGENTAREA_TASK_OUTAGE_RETRY_WINDOW", errors.New("must be positive"))
	}
	if s.OutageWait.Deadline <= 0 {
		l.Fail("AGENTAREA_TASK_OUTAGE_WAIT_DEADLINE", errors.New("must be positive"))
	}
	if v, ok := l.OptionalEnv("AGENTAREA_TASK_SKILLS_WINDOW_SHARE"); ok {
		f, err := strconv.ParseFloat(v, 64)
		if err != nil || f <= 0 || f > 1 {
			l.Fail("AGENTAREA_TASK_SKILLS_WINDOW_SHARE", errors.New("must be a number greater than 0 and at most 1"))
		} else {
			s.SkillsWindowShare = f
		}
	}
	return s
}
