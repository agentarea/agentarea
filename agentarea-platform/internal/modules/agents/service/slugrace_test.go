package service

import (
	"errors"
	"testing"
)

func TestRetryWhenRerunsOnlyALostSlug(t *testing.T) {
	lost, other := errors.New("lost"), errors.New("other")
	isLost := func(err error) bool { return errors.Is(err, lost) }
	n := 0
	if err := retryWhen(isLost, func() error {
		n++
		if n < 2 {
			return lost
		}
		return nil
	}); err != nil || n != 2 {
		t.Fatalf("n=%d err=%v", n, err)
	}
	n = 0
	if err := retryWhen(isLost, func() error { n++; return lost }); !errors.Is(err, lost) || n != slugAttempts {
		t.Fatalf("n=%d err=%v", n, err)
	}
	n = 0
	if err := retryWhen(isLost, func() error { n++; return other }); !errors.Is(err, other) || n != 1 {
		t.Fatalf("n=%d err=%v", n, err)
	}
}
