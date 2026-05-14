import { redirect } from "next/navigation";
import { getServerSession } from "@ory/nextjs/app";

export default async function RootPage() {
  const session = await getServerSession();

  if (session?.identity) {
    redirect("/dashboard");
  } else {
    redirect("/auth/login");
  }
}
