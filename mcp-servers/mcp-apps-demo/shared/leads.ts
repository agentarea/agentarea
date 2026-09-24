/** Columns the view renders. Any dataset bound to the app must provide them. */
export const LEAD_COLUMNS = ["id", "company", "industry", "status"] as const;

export const LEAD_STATUSES = ["new", "contacted", "qualified", "lost"] as const;
