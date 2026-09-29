export type TaskParameterRef = {
  id: string;
  name?: string | null;
  description?: string | null;
};

export type NormalizedTaskParameters = {
  text: string;
  files: string[];
  skills: TaskParameterRef[];
  mcps: TaskParameterRef[];
  rest: Record<string, unknown>;
};

const STRUCTURED_KEYS = new Set([
  "text",
  "files",
  "skills",
  "mcps",
  "mcp",
  "mcp_servers",
]);

function normalizeRef(value: unknown): TaskParameterRef | null {
  if (typeof value === "string" && value.trim()) {
    return { id: value.trim(), name: value.trim() };
  }
  if (!value || typeof value !== "object") return null;

  const record = value as Record<string, unknown>;
  const id = record.id ?? record.instance_id ?? record.skill_id;
  if (typeof id !== "string" || !id.trim()) return null;

  return {
    id: id.trim(),
    name: typeof record.name === "string" ? record.name : null,
    description:
      typeof record.description === "string" ? record.description : null,
  };
}

function normalizeRefs(value: unknown): TaskParameterRef[] {
  if (!Array.isArray(value)) return [];
  return value.map(normalizeRef).filter(Boolean) as TaskParameterRef[];
}

function normalizeFiles(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((file) => {
      if (typeof file === "string") return file.trim();
      if (!file || typeof file !== "object") return "";
      const record = file as Record<string, unknown>;
      const path = record.path ?? record.name ?? record.url;
      return typeof path === "string" ? path.trim() : "";
    })
    .filter(Boolean);
}

export function normalizeTaskParameters(
  value: unknown
): NormalizedTaskParameters {
  const source =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};

  const rest = Object.fromEntries(
    Object.entries(source).filter(([key]) => !STRUCTURED_KEYS.has(key))
  );

  return {
    text: typeof source.text === "string" ? source.text : "",
    files: normalizeFiles(source.files),
    skills: normalizeRefs(source.skills),
    mcps: normalizeRefs(source.mcps ?? source.mcp ?? source.mcp_servers),
    rest,
  };
}

export function composeTaskParameters({
  text,
  files,
  skills,
  mcps,
  rest,
}: NormalizedTaskParameters): Record<string, unknown> {
  const next: Record<string, unknown> = { ...rest };
  const trimmedText = text.trim();

  if (trimmedText) {
    next.text = trimmedText;
  } else {
    delete next.text;
  }

  if (files.length > 0) {
    next.files = files;
  } else {
    delete next.files;
  }

  if (skills.length > 0) {
    next.skills = skills.map(({ id, name, description }) => ({
      id,
      ...(name ? { name } : {}),
      ...(description ? { description } : {}),
    }));
  } else {
    delete next.skills;
  }

  if (mcps.length > 0) {
    next.mcps = mcps.map(({ id, name, description }) => ({
      id,
      ...(name ? { name } : {}),
      ...(description ? { description } : {}),
    }));
  } else {
    delete next.mcps;
  }

  return next;
}

export function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}
