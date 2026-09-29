import { redirect } from "next/navigation";
import { getServerSession } from "@/lib/ory";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";
import { rootLandingPath } from "@/lib/workspace-routes";

export default async function RootPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await getServerSession();

  if (session?.identity) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(await searchParams)) {
      if (typeof value === "string") query.set(key, value);
    }
    redirect(await getPersonalWorkspacePath(rootLandingPath(query)));
  } else {
    redirect("/auth/login");
  }
}
