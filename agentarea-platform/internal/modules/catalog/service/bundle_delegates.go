package service

import (
	"fmt"
	"strings"
)

// agentOrder is the agents with each delegate before the agents that hand
// work to it; cycle is the first loop of delegation found, nil when there is none.
func agentOrder(agents []BundleAgent) ([]BundleAgent, []string) {
	return dependencyOrder(agents, func(a BundleAgent) string { return a.Key }, func(a BundleAgent) []string { return a.Delegates })
}

// dependencyOrder is items with each one after the items it depends on;
// cycle is the first loop found, and then items stay in their order.
func dependencyOrder[T any](items []T, key func(T) string, deps func(T) []string) ([]T, []string) {
	byKey := map[string]T{}
	for _, it := range items {
		if _, dup := byKey[key(it)]; !dup {
			byKey[key(it)] = it
		}
	}
	const visiting, done = 1, 2
	state := map[string]int{}
	var order []T
	var path, cycle []string
	var visit func(it T)
	visit = func(it T) {
		k := key(it)
		state[k] = visiting
		path = append(path, k)
		for _, d := range deps(it) {
			next, known := byKey[d]
			switch {
			case !known || cycle != nil:
			case state[d] == visiting:
				for i, p := range path {
					if p == d {
						cycle = append(append([]string{}, path[i:]...), d)
						break
					}
				}
			case state[d] == 0:
				visit(next)
			}
		}
		path = path[:len(path)-1]
		state[k] = done
		order = append(order, it)
	}
	for _, it := range items {
		if state[key(it)] == 0 {
			visit(it)
		}
	}
	if cycle != nil {
		return items, cycle
	}
	return order, nil
}

func cycleText(cycle []string) string {
	return "agents delegate in a cycle: " + strings.Join(cycle, " -> ")
}

// delegateProblem is why an agent's delegates cannot be installed, "" when they can.
func delegateProblem(a BundleAgent, agentKeys map[string]bool) string {
	for _, d := range a.Delegates {
		if !agentKeys[d] {
			return fmt.Sprintf("agent '%s' delegates to '%s', which is not an agent of this bundle", a.Key, d)
		}
	}
	return ""
}
