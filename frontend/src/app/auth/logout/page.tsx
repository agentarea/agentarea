import { getLogoutFlow } from "@ory/nextjs/app"
import { redirect } from "next/navigation"

export default async function LogoutPage() {
  const flow = await getLogoutFlow()

  // If we got a logout URL, redirect to it to complete the logout
  if (flow?.logout_url) {
    redirect(flow.logout_url)
  }

  // Fallback: redirect to login if something went wrong
  redirect("/auth/login")
}
