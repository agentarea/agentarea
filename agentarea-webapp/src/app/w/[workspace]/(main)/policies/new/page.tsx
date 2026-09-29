import type { Metadata } from "next";
import { PolicyEditorPageData } from "../components/PolicyEditorPageData";

export const metadata: Metadata = {
  title: "New Policy",
};

export default function NewPolicyPage() {
  return <PolicyEditorPageData />;
}
