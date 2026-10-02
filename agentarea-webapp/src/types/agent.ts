import type { AgentResponse } from "@/api/client/types.gen";

export interface ModelInfo {
  provider_name?: string;
  provider_icon_url?: string;
  model_display_name?: string;
  config_name?: string;
}

export type Agent = Omit<AgentResponse, "slug"> & {
  slug?: string | null;
  model_info?: ModelInfo | null;
  icon?: string;
};

export type AgentSkillView = {
  id: string;
  name: string;
  description?: string | null;
};

export function agentSkillViews(skills: Agent["skills"]): AgentSkillView[] {
  const views: AgentSkillView[] = [];
  for (const skill of skills ?? []) {
    const id = skill.id;
    const name = skill.name;
    if (typeof id !== "string" || typeof name !== "string") continue;
    const description = skill.description;
    views.push({
      id,
      name,
      ...(typeof description === "string" || description === null
        ? { description }
        : {}),
    });
  }
  return views;
}

/**
 * Builds the canonical path to an agent's detail page.
 * Prefers the workspace-scoped slug (nicer URLs, stable across renames-by-id),
 * falling back to the UUID when no slug is present. The backend resolves both.
 */
export function agentPath(
  agent: { slug?: string | null; id: string },
  suffix = ""
): string {
  const ref = agent.slug || agent.id;
  return `/agents/${ref}${suffix}`;
}
