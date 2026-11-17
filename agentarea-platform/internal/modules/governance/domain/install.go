package domain

import (
	"fmt"
	"strings"
)

// InstallDecision is CatalogInstallDecision.
type InstallDecision struct {
	Allowed bool
	Reason  string
}

// DecideCatalogInstall is decide_catalog_install: whether an item of
// registryID labelled trust may be installed under the enabled rules of the
// layers that apply. In each layer a deny on the registry or its trust wins,
// and a layer with an allow rule admits only what one of them names.
func DecideCatalogInstall(rules []Rule, registryID, trust string) InstallDecision {
	targets := map[string]bool{"registry:" + registryID: true, "registry_trust:" + trust: true}
	type layerKey struct{ subjectType, subjectID string }
	var order []layerKey
	layers := map[layerKey][]Rule{}
	for _, r := range rules {
		kind, _, _ := strings.Cut(r.Target, ":")
		if !r.Enabled || (kind != "registry" && kind != "registry_trust") {
			continue
		}
		k := layerKey{r.SubjectType, r.SubjectID}
		if _, ok := layers[k]; !ok {
			order = append(order, k)
		}
		layers[k] = append(layers[k], r)
	}
	for _, k := range order {
		var allows []Rule
		for _, r := range layers[k] {
			if r.Effect == "deny" && targets[r.Target] {
				return InstallDecision{false, fmt.Sprintf("denied by %s for %s %s", r.Target, k.subjectType, k.subjectID)}
			}
			if r.Effect == "allow" {
				allows = append(allows, r)
			}
		}
		if len(allows) == 0 {
			continue
		}
		named := false
		for _, r := range allows {
			named = named || targets[r.Target]
		}
		if !named {
			return InstallDecision{false, fmt.Sprintf("registry %s (%s) is not among the registries %s %s allows installs from",
				registryID, trust, k.subjectType, k.subjectID)}
		}
	}
	return InstallDecision{true, "allowed by install policy"}
}
