import { redirect } from "next/navigation";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";
import { WORKSPACE_HOME } from "@/lib/workspace-routes";

export const dynamic = "force-dynamic";

/** Kratos returns here after sign-in (`default_browser_return_url`). */
export default async function SignedInLanding() {
  redirect(await getPersonalWorkspacePath(WORKSPACE_HOME));
}
