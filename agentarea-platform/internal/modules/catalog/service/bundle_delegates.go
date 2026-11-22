package service

import (
	"fmt"
	"strings"
)

// agentOrder is the agents with each delegate before the agents that hand
// work to it; cycle is the first loop of delegation found, nil when there is none.
func agentOrder(agents []BundleAgent) ([]BundleAgent, []string) {
	byKey := map[string]BundleAgent{}
	for _, a := range agents {
		if _, dup := byKey[a.Key]; !dup {
			byKey[a.Key] = a
		}
	}
	const visiting, done = 1, 2
	state := map[string]int{}
	var order []BundleAgent
	var path, cycle []string
	var visit func(a BundleAgent)
	visit = func(a BundleAgent) {
		state[a.Key] = visiting
		path = append(path, a.Key)
		for _, d := range a.Delegates {
			next, known := byKey[d]
			switch {
			case !known || cycle != nil:
			case state[d] == visiting:
				for i, k := range path {
					if k == d {
						cycle = append(append([]string{}, path[i:]...), d)
						break
					}
				}
			case state[d] == 0:
				visit(next)
			}
		}
		path = path[:len(path)-1]
		state[a.Key] = done
		order = append(order, a)
	}
	for _, a := range agents {
		if state[a.Key] == 0 {
			visit(a)
		}
	}
	if cycle != nil {
		return agents, cycle
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
