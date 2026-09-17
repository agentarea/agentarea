import { redirect } from "next/navigation";

interface Props {
  params: Promise<{ id: string }>;
}

/** The automation page is the form now, so this URL has nothing of its own. */
export default async function EditTriggerPage({ params }: Props) {
  const { id } = await params;
  redirect(`/triggers/${id}`);
}
