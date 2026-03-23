import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { AddOpenAPIForm } from "./form";

export default function AddOpenAPIPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Connections", href: "/mcp-servers" },
          { label: "Add OpenAPI Connection" },
        ],
        description: "Connect an OpenAPI-based REST API to your workspace",
        backLink: {
          label: "Back to Connections",
          href: "/mcp-servers",
        },
      }}
    >
      <AddOpenAPIForm />
    </ContentBlock>
  );
}
