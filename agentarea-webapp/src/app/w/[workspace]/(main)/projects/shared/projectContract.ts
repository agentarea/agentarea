import type { ProjectCreate, ProjectResponse } from "@/api/client/types.gen";

/** What the project form edits: the project's own text fields, as typed. */
export type ProjectFormValues = {
  name: string;
  description: string;
  instructions: string;
};

/** A saved project as form values; an empty form when there is none yet. */
export function toProjectFormValues(
  project?: ProjectResponse | null
): ProjectFormValues {
  return {
    name: project?.name ?? "",
    description: project?.description ?? "",
    instructions: project?.instructions ?? "",
  };
}

/** Form values as the API contract: trimmed, with a blank note sent as null. */
export function toProjectPayload(values: ProjectFormValues): ProjectCreate {
  return {
    name: values.name.trim(),
    description: values.description.trim() || null,
    instructions: values.instructions.trim() || null,
  };
}
