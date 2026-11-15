package app

// Subcommands are the names the open build runs: its implemented roles and
// its commands (api/contract checks them against the Python CLI).
func Subcommands() []string {
	var out []string
	for _, r := range roles() {
		if r.lands == "" {
			out = append(out, r.name)
		}
	}
	for _, c := range commands() {
		out = append(out, c.name)
	}
	return out
}
