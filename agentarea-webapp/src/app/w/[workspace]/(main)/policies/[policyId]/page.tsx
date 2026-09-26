import type { Metadata } from "next";
import { PolicyEditorPageData } from "../components/PolicyEditorPageData";

export const metadata: Metadata = {
  title: "Edit Policy",
};

export default async function EditPolicyPage({
  params,
}: {
  params: Promise<{ policyId: string }>;
}) {
  const { policyId } = await params;
  return <PolicyEditorPageData policyId={policyId} />;
}
