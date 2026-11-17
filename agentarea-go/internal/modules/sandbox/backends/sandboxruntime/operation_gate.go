package sandboxruntime

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
)

// operationGate fences live sandbox work against retirement of the same
// binding. Execution, uploads, listings, hydration and download streams hold
// the read side for their whole duration; retirement holds the write side, so
// a task binding is never torn down underneath work that is still in flight.
type operationGate struct {
	mu      sync.Mutex
	entries map[string]*gateEntry
}

type gateEntry struct {
	rw   sync.RWMutex
	refs int
}

func newOperationGate() *operationGate {
	return &operationGate{entries: make(map[string]*gateEntry)}
}

// TaskOperationGate is the same fence exposed for runtimes that own their task
// lifecycle directly. Every ManagedRuntime has to be able to hold one fence
// across a composite operation, so this is shared rather than reimplemented.
type TaskOperationGate struct {
	provider string
	gate     *operationGate
	store    *SessionStore
}

func NewTaskOperationGate(provider string) *TaskOperationGate {
	return &TaskOperationGate{provider: provider, gate: newOperationGate()}
}

// NewDistributedTaskOperationGate coordinates external-provider work through
// the same Redis store that owns provider bindings. The API manager and the
// standalone runner are separate processes, so an in-memory mutex cannot fence
// OpenSandbox/E2B retirement against work running elsewhere.
func NewDistributedTaskOperationGate(provider string, store *SessionStore) *TaskOperationGate {
	return &TaskOperationGate{provider: provider, store: store}
}

// ready refuses to run unfenced. A runtime assembled without a gate would
// otherwise let retirement race live work with no signal at all.
func (g *TaskOperationGate) ready() error {
	if g == nil || (g.gate == nil && g.store == nil) || (g.gate != nil && g.store != nil) {
		return fmt.Errorf("sandbox runtime was assembled without a task operation gate")
	}
	return nil
}

// BeginOperation holds the read side for one binding until release runs. A
// context that already carries this binding's fence passes straight through, so
// nested steps of one composite operation never re-acquire it.
func (g *TaskOperationGate) BeginOperation(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	if err := g.ready(); err != nil {
		return nil, nil, err
	}
	key := gateKey(g.provider, workspaceID, taskID)
	if fenceHeld(ctx, key) {
		return ctx, func() {}, nil
	}
	var (
		fenced  context.Context
		release func()
		err     error
	)
	if g.store != nil {
		fenced, release, err = g.store.acquireOperationFence(ctx, g.provider, workspaceID, taskID)
	} else {
		release, err = g.gate.acquire(ctx, key, false)
		fenced = ctx
	}
	if err != nil {
		return nil, nil, err
	}
	fenced, token := markFenceHeld(fenced, key)
	return fenced, func() {
		token.released.Store(true)
		release()
	}, nil
}

// BeginRetirement holds the write side, so retirement waits for every in-flight
// operation on the binding and blocks new ones from starting.
func (g *TaskOperationGate) BeginRetirement(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	if err := g.ready(); err != nil {
		return nil, nil, err
	}
	key := gateKey(g.provider, workspaceID, taskID)
	if fenceHeld(ctx, key) {
		return nil, nil, fmt.Errorf("sandbox retirement cannot run inside a live operation on the same task")
	}
	if g.store != nil {
		return g.store.acquireRetirementFence(ctx, g.provider, workspaceID, taskID)
	}
	release, err := g.gate.acquire(ctx, key, true)
	return ctx, release, err
}

func gateKey(provider, workspaceID, taskID string) string {
	return provider + "\x00" + workspaceID + "\x00" + taskID
}

// heldFence marks a context whose caller already holds the read side for one
// binding. A composing layer (workspace hydration followed by execution) takes
// the fence once and passes the marked context down, so the inner steps do not
// re-acquire it. Re-acquiring would be worse than redundant: Go's RWMutex
// queues a pending writer ahead of later readers, so a second RLock on the same
// goroutine deadlocks against a retirement that arrived in between.
type heldFence struct{ key string }

// fenceToken makes the marker stop counting once the fence it refers to has
// been released. A context outlives the operation that marked it, so without
// this a caller reusing that context afterwards would be told the fence was
// still held, get a no-op release, and run completely unfenced.
type fenceToken struct{ released atomic.Bool }

func fenceHeld(ctx context.Context, key string) bool {
	token, ok := ctx.Value(heldFence{key: key}).(*fenceToken)
	return ok && token != nil && !token.released.Load()
}

func markFenceHeld(ctx context.Context, key string) (context.Context, *fenceToken) {
	token := &fenceToken{}
	return context.WithValue(ctx, heldFence{key: key}, token), token
}

// reserve pins the per-binding entry so it survives in the map for as long as
// any holder or waiter exists. Without the reference count two callers could
// otherwise end up serialized by two different mutexes for the same binding.
func (g *operationGate) reserve(key string) *gateEntry {
	g.mu.Lock()
	defer g.mu.Unlock()
	entry := g.entries[key]
	if entry == nil {
		entry = &gateEntry{}
		g.entries[key] = entry
	}
	entry.refs++
	return entry
}

func (g *operationGate) release(key string, entry *gateEntry) {
	g.mu.Lock()
	defer g.mu.Unlock()
	entry.refs--
	if entry.refs == 0 {
		delete(g.entries, key)
	}
}

// acquire blocks until the requested side of the binding lock is held or ctx
// ends. A caller that gives up hands ownership to a detached releaser, so an
// abandoned acquisition can never leave the lock permanently held.
func (g *operationGate) acquire(ctx context.Context, key string, write bool) (func(), error) {
	entry := g.reserve(key)
	acquired := make(chan struct{})
	go func() {
		if write {
			entry.rw.Lock()
		} else {
			entry.rw.RLock()
		}
		close(acquired)
	}()
	unlock := func() {
		if write {
			entry.rw.Unlock()
		} else {
			entry.rw.RUnlock()
		}
		g.release(key, entry)
	}
	select {
	case <-acquired:
		var once sync.Once
		return func() { once.Do(unlock) }, nil
	case <-ctx.Done():
		go func() {
			<-acquired
			unlock()
		}()
		return nil, ctx.Err()
	}
}
