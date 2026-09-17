import { redirect } from "next/navigation";
import type { OryPageParams } from "@/lib/ory";

export default async function SettingsRedirect(props: OryPageParams) {
  const params = await props.searchParams;
  const query = new URLSearchParams();

  for (const [name, value] of Object.entries(params)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== undefined) query.append(name, item);
    }
  }

  redirect(`/settings${query.size ? `?${query}` : ""}`);
}
