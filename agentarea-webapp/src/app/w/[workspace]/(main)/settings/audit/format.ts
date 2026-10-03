const CREATE_COLOR =
  "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400";
const UPDATE_COLOR =
  "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400";
const DELETE_COLOR =
  "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400";
const ATTENTION_COLOR =
  "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400";

const ACTION_COLORS: Record<string, string> = {
  create: CREATE_COLOR,
  invite: CREATE_COLOR,
  grant: CREATE_COLOR,
  allowed: CREATE_COLOR,
  approved: CREATE_COLOR,
  update: UPDATE_COLOR,
  rotate: UPDATE_COLOR,
  set_enabled: UPDATE_COLOR,
  delete: DELETE_COLOR,
  remove: DELETE_COLOR,
  revoke: DELETE_COLOR,
  invitation_revoke: DELETE_COLOR,
  denied: DELETE_COLOR,
  approval_required: ATTENTION_COLOR,
};

export function auditVerb(action: string): string {
  return action.split(".").pop() || "";
}

export function auditActionColor(action: string): string {
  const verb = action.split(".").pop() || "";
  return (
    ACTION_COLORS[verb] ||
    "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-300"
  );
}

export function formatAuditTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
