export type SkillSourceType = 'content' | 'github' | 'upload';

export interface Skill {
  id: string;
  name: string;
  description: string | null;
  source_type: SkillSourceType;
  source_url: string | null;
  has_files: boolean;
  workspace_id: string;
  created_at: string;
  updated_at: string;
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
