package polling

import (
	"errors"
	"testing"
)

func TestPollOutcome(t *testing.T) {
	failure := errors.New("boom")
	cases := []struct {
		step     string
		err      error
		canceled bool
		want     string
	}{
		{step: stepRecord, want: "ok"},
		{step: stepCredentials, err: failure, want: "credentials_failed"},
		{step: stepFetch, err: failure, want: "fetch_failed"},
		{step: stepPublish, err: failure, want: "publish_failed"},
		{step: stepRecord, err: failure, want: "record_failed"},
		{step: stepFetch, err: failure, canceled: true, want: "canceled"},
	}
	for _, tc := range cases {
		if got := pollOutcome(tc.step, tc.err, tc.canceled); got != tc.want {
			t.Fatalf("pollOutcome(%s, %v, %v) = %q, want %q", tc.step, tc.err, tc.canceled, got, tc.want)
		}
	}
}
