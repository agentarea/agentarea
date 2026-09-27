// Hard-coded, not configurable: a write journey must never run anywhere but
// the dedicated perf workspace. This is the one thing in the suite that is
// not allowed to be an env var, because an env var can be a wrong argument
// away from pointing writes at somebody's real workspace.
import { WORKSPACE } from "../config.js";

export const PERF_WORKSPACE = "perf-k6";
export const IS_PERF_WORKSPACE = WORKSPACE === PERF_WORKSPACE;

// Call at the top of every write journey's run(). Read-only browse journeys
// never call this and work against any workspace.
export function assertWriteAllowed(journeyName) {
  if (!IS_PERF_WORKSPACE) {
    throw new Error(
      `Refusing to run "${journeyName}": WORKSPACE is "${WORKSPACE}", not "${PERF_WORKSPACE}". ` +
        "Write journeys (create/update/delete) are locked to the dedicated perf-k6 workspace " +
        "so a wrong -e can never touch real data. Read-only browse journeys work against any workspace."
    );
  }
}
