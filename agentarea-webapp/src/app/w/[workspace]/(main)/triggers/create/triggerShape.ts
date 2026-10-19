/**
 * A schedule comes due carrying nothing with it, so the task text is the only
 * thing that can tell the agent what to do — and the backend rejects a schedule
 * saved without one (`trigger_service.py`, `_validate_cron_configuration`).
 *
 * A stream trigger is exempt: the event it fires on is attached to the task, so
 * the text is the instruction for handling it and may be left empty.
 */
export function requiresTaskText(triggerType: string): boolean {
  return triggerType === "cron";
}
