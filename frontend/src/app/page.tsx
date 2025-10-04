import { getServerSession } from "@ory/nextjs/app";
import { redirect } from "next/navigation";

export default async function RootPage() {
  const session = await getServerSession();

  console.log(session);

  if (session?.identity) {
    redirect("/workplace");
  } else {
    redirect("/auth/login");
  }
}
