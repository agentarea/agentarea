import { InstanceActivitySection } from "./InstanceActivitySection";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ConnectionActivityPage({ params }: Props) {
  const { id } = await params;

  return (
    <div className="h-full overflow-y-auto px-4 py-5">
      <InstanceActivitySection instanceId={id} />
    </div>
  );
}
