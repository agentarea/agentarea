import { redirect } from "next/navigation";
import { deepLinkPath } from "@/lib/deep-link";
import { SKILL_IMPORT_QUERY_PARAM } from "@/lib/skill-import";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";

/**
 * Where the landing's "Install in AgentArea" sends someone. The landing cannot
 * know their workspace, so this lands them in the personal one.
 */
export default async function SkillImportPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const value = (await searchParams)[SKILL_IMPORT_QUERY_PARAM];
  redirect(
    await getPersonalWorkspacePath(
      deepLinkPath("/skills/create", SKILL_IMPORT_QUERY_PARAM, value)
    )
  );
}
