import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { AddOpenAPIForm } from "./form";
import AddOpenAPIHeaderControls from "./HeaderControls";

export const metadata: Metadata = {
  title: "Add OpenAPI Connection",
};

export default async function AddOpenAPIPage() {
  const t = await getTranslations("MCPServersPage");
  const tForm = await getTranslations("OpenAPIForm");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          { label: tForm("title") },
        ],
        controls: <AddOpenAPIHeaderControls />,
      }}
    >
      <AddOpenAPIForm />
    </ContentBlock>
  );
}
