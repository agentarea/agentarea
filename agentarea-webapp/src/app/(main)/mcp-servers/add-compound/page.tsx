import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { AddCompoundForm } from "./form";

export default function AddCompoundPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Connections", href: "/mcp-servers" },
          { label: "Add Compound MCP" },
        ],
        description: "Combine multiple MCP servers into one endpoint — other agents connect to it like any MCP server",
        backLink: {
          label: "Back to Connections",
          href: "/mcp-servers",
        },
      }}
    >
      <AddCompoundForm />
    </ContentBlock>
  );
}
