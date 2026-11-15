package domain

import (
	"fmt"
	"sort"
)

// reservedTaskParameter reports the keys only the trigger that received an event may write (reserved_task_parameters.py).
func reservedTaskParameter(k string) bool {
	switch k {
	case "delivery_address", "session", "follow_up_message", "trigger_event", "trigger_event_file":
		return true
	}
	return false
}

// DropReserved removes the reserved keys of an edit's parameters.
func DropReserved(p map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range p {
		if !reservedTaskParameter(k) {
			out[k] = v
		}
	}
	return out
}

// RefuseReserved reports the reserved keys a caller supplied, in name order.
func RefuseReserved(p map[string]any) error {
	var names []string
	for k := range p {
		if reservedTaskParameter(k) {
			names = append(names, k)
		}
	}
	if len(names) == 0 {
		return nil
	}
	sort.Strings(names)
	return Invalid(fmt.Sprintf("%s is set by the trigger that received the event and cannot be supplied", names[0]))
}
