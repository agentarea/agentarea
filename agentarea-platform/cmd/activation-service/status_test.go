package main

import (
	"sync"
	"sync/atomic"
	"testing"
)

func TestOnlyOneConcurrentActivationClaimsThePod(t *testing.T) {
	s := newTestServer(t)
	var won atomic.Int32
	var wg sync.WaitGroup
	for range 32 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if s.claimActivation() {
				won.Add(1)
			}
		}()
	}
	wg.Wait()
	if won.Load() != 1 || s.currentStatus() != "activating" {
		t.Fatalf("claims won = %d, status = %q; want 1, activating", won.Load(), s.currentStatus())
	}
}
