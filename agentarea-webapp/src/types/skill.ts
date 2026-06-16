export type SkillSourceType = "content" | "github" | "zip" | "path";
export type SkillNetworkScope = "private" | "ingress" | "egress";

export interface Skill {
  id: string;
  name: string;
  description: string | null;
  source_type: SkillSourceType;
  source_url: string | null;
  network_scope: SkillNetworkScope;
  workspace_id: string;
  created_at: string;
  updated_at: string;
  is_catalog?: boolean | null;
  registry_item_id?: string | null;
  update_available?: boolean | null;
}

export interface PaginatedSkills {
  items: Skill[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface SkillContent {
  id: string;
  name: string;
  content: string;
}

export interface SkillFile {
  path: string;
  size: number;
  url?: string | null;
}

export interface SkillCreateRequest {
  content?: string | null;
  github_url?: string | null;
  name?: string | null;
  description?: string | null;
}

export interface SkillUpdateRequest {
  name?: string | null;
  description?: string | null;
  content?: string | null;
}
