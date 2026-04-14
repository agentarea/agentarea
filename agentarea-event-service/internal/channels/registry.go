package channels

import "sync"

var (
	mu        sync.RWMutex
	factories = map[string]Factory{}
)

// Register adds a channel factory by extractor name (e.g. "telegram_polling").
func Register(name string, f Factory) {
	mu.Lock()
	defer mu.Unlock()
	factories[name] = f
}

// Get returns a channel factory by extractor name, or nil if not found.
func Get(name string) Factory {
	mu.RLock()
	defer mu.RUnlock()
	return factories[name]
}
