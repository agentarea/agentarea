import { redirect } from "next/navigation";

/** The page moved to /models, which is what the sidebar has always called it. */
export default function ProviderConfigsRedirect() {
  redirect("/models");
}
