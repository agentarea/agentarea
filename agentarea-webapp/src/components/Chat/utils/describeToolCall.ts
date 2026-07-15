/**
 * Turn a raw tool call into a human-readable action phrase, the way Codex does
 * ("Ran build.sh", "Read config.yaml", "Searched the web for ...") instead of
 * the unhelpful "Tool call: <tool_name>".
 */

function asString(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() ? v : undefined;
}

function pick(args: Record<string, unknown> | undefined, keys: string[]): string | undefined {
  if (!args) return undefined;
  for (const k of keys) {
    const v = asString(args[k]);
    if (v) return v;
  }
  return undefined;
}

function basename(p: string): string {
  return p.trim().split(/[?#]/)[0].split(/[\\/]/).pop() || p;
}

function truncate(s: string, max = 64): string {
  const oneLine = s.replace(/\s+/g, " ").trim();
  return oneLine.length > max ? `${oneLine.slice(0, max - 1)}…` : oneLine;
}

function titleize(name: string): string {
  const cleaned = name.replace(/^mcp__/, "").replace(/__/g, " ").replace(/[_-]+/g, " ").trim();
  return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : name;
}

export interface ToolCallDescription {
  /** Natural-language action, e.g. "Read template.md". */
  text: string;
  /** Optional monospace detail to show after the action (command, query). */
  code?: string;
}

export function describeToolCall(
  toolName: string,
  args?: Record<string, unknown> | null
): ToolCallDescription {
  const a = args || {};
  const n = (toolName || "").toLowerCase();

  // Skills
  if (n === "activate_skill" || n.includes("skill")) {
    const skill = pick(a, ["skill", "name", "skill_name", "skill_id"]);
    return { text: skill ? `Activated skill ${skill}` : "Activated a skill" };
  }

  // Shell / command execution
  if (/(shell|bash|terminal|command|cmd|execute|exec|run_)/.test(n)) {
    const cmd = pick(a, ["command", "cmd", "script", "code"]);
    return cmd ? { text: "Ran", code: truncate(cmd) } : { text: "Ran a command" };
  }

  // Agent delegation: delegate_to_<agent>
  if (n.startsWith("delegate") || n.includes("call_agent") || n.includes("sub_agent")) {
    const target = n.startsWith("delegate_to_") ? titleize(toolName.slice("delegate_to_".length)) : undefined;
    const fromArg = pick(a, ["agent", "agent_name", "target"]);
    const who = target || fromArg;
    return { text: who ? `Delegated to ${who}` : "Delegated to another agent" };
  }

  // File ops
  if (/^(read_file|read|cat|open_file)$/.test(n) || n.includes("read_file")) {
    const path = pick(a, ["path", "file", "filename", "file_path"]);
    return { text: path ? `Read ${basename(path)}` : "Read a file" };
  }
  if (n.includes("write_file") || n.includes("create_file") || n === "write") {
    const path = pick(a, ["path", "file", "filename", "file_path"]);
    return { text: path ? `Wrote ${basename(path)}` : "Wrote a file" };
  }
  if (n.includes("edit_file") || n.includes("apply_patch") || n.includes("patch")) {
    const path = pick(a, ["path", "file", "filename", "file_path"]);
    return { text: path ? `Edited ${basename(path)}` : "Edited a file" };
  }
  if (n.includes("list") || n.includes("glob") || n.includes("ls")) {
    return { text: "Listed files" };
  }

  // Web
  if (n.includes("web_search") || n.includes("google_search") || n === "search" || n.endsWith("_search")) {
    const q = pick(a, ["query", "q", "search", "text"]);
    // GitHub-style searches read better with the source name.
    if (n.includes("github")) return q ? { text: "Searched GitHub", code: truncate(q, 48) } : { text: "Searched GitHub" };
    return q ? { text: "Searched the web for", code: truncate(q, 48) } : { text: "Searched the web" };
  }
  if (n.includes("fetch") || n.includes("http") || n.includes("url") || n.includes("browse") || n.includes("curl")) {
    const url = pick(a, ["url", "href", "uri", "link"]);
    return { text: url ? `Fetched ${truncate(url, 56)}` : "Fetched a URL" };
  }

  // Database
  if (n.includes("postgres") || n.includes("sql") || n.includes("query") || n.includes("database")) {
    return { text: "Queried the database" };
  }

  // GitHub specifics
  if (n.includes("github")) {
    if (n.includes("get_file") || n.includes("read")) {
      const path = pick(a, ["path", "file"]);
      return { text: path ? `Read GitHub file ${basename(path)}` : "Read a GitHub file" };
    }
    if (n.includes("pull_request") || n.includes("pr")) return { text: "Opened a pull request" };
    if (n.includes("issue")) return { text: "Worked with GitHub issues" };
    return { text: titleize(toolName) };
  }

  // Messaging
  if (n.includes("slack") || n.includes("discord") || n.includes("telegram") || n.includes("post_message") || n.includes("notify")) {
    const channel = pick(a, ["channel", "to", "recipient"]);
    return { text: channel ? `Sent a message to ${channel}` : "Sent a message" };
  }

  // Memory
  if (n.includes("recall") || n.includes("memory") || n.includes("remember") || n.includes("history")) {
    return { text: "Recalled history" };
  }

  if (n === "completion" || n === "finish" || n === "done") {
    return { text: "Finished the task" };
  }

  // Fallback: titleized tool name (much friendlier than the raw snake_case).
  return { text: titleize(toolName) };
}

/**
 * Coarse action bucket for a tool, used to build a Codex-style group summary
 * ("Read 5 files, ran 11 commands, edited 2 files"). Mirrors the branching in
 * describeToolCall but collapses everything to a single verb category.
 */
type ToolCategory =
  | "read"
  | "edited"
  | "wrote"
  | "ran"
  | "searched"
  | "fetched"
  | "queried"
  | "listed"
  | "sent"
  | "skill"
  | "delegated"
  | "other";

function toolCategory(toolName: string): ToolCategory {
  const n = (toolName || "").toLowerCase();
  if (n === "activate_skill" || n.includes("skill")) return "skill";
  if (/(shell|bash|terminal|command|cmd|execute|exec|run_)/.test(n)) return "ran";
  if (n.startsWith("delegate") || n.includes("call_agent") || n.includes("sub_agent")) return "delegated";
  if (n.includes("edit_file") || n.includes("apply_patch") || n.includes("patch")) return "edited";
  if (n.includes("write_file") || n.includes("create_file") || n === "write") return "wrote";
  if (/^(read_file|read|cat|open_file)$/.test(n) || n.includes("read_file")) return "read";
  if (n.includes("web_search") || n.includes("google_search") || n === "search" || n.endsWith("_search")) return "searched";
  if (n.includes("fetch") || n.includes("http") || n.includes("url") || n.includes("browse") || n.includes("curl")) return "fetched";
  if (n.includes("postgres") || n.includes("sql") || n.includes("query") || n.includes("database")) return "queried";
  if (n.includes("slack") || n.includes("discord") || n.includes("telegram") || n.includes("post_message") || n.includes("notify")) return "sent";
  if (n.includes("list") || n.includes("glob") || n.includes("ls")) return "listed";
  return "other";
}

const CATEGORY_WORDS: Record<ToolCategory, [verb: string, noun: string]> = {
  read: ["read", "file"],
  edited: ["edited", "file"],
  wrote: ["wrote", "file"],
  ran: ["ran", "command"],
  searched: ["searched", "search"],
  fetched: ["fetched", "page"],
  queried: ["ran", "query"],
  listed: ["listed", "directory"],
  sent: ["sent", "message"],
  skill: ["used", "skill"],
  delegated: ["delegated to", "agent"],
  other: ["ran", "tool"],
};

function pluralize(noun: string, n: number): string {
  if (n === 1) return noun;
  if (/(s|sh|ch|x|z)$/.test(noun)) return `${noun}es`;
  if (/[^aeiou]y$/.test(noun)) return `${noun.slice(0, -1)}ies`;
  return `${noun}s`;
}

/**
 * Build a single-line summary of a tool group, e.g. "Read 5 files, ran 11
 * commands, edited 2 files". Categories appear in order of first occurrence.
 */
export function summarizeToolGroup(toolNames: string[]): string {
  const counts = new Map<ToolCategory, number>();
  for (const name of toolNames) {
    const cat = toolCategory(name);
    counts.set(cat, (counts.get(cat) || 0) + 1);
  }
  const parts = [...counts].map(([cat, n]) => {
    const [verb, noun] = CATEGORY_WORDS[cat];
    return `${verb} ${n} ${pluralize(noun, n)}`;
  });
  if (parts.length) parts[0] = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
  return parts.join(", ");
}
