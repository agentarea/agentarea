package service

import "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"

const slugAttempts = 3

// retrySlug reruns a slug scan and insert that lost the slug to a
// concurrent insert.
func retrySlug(fn func() error) error { return retryWhen(store.SlugTaken, fn) }

func retryWhen(lost func(error) bool, fn func() error) error {
	var err error
	for range slugAttempts {
		if err = fn(); !lost(err) {
			return err
		}
	}
	return err
}
